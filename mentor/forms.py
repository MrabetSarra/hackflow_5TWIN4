from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from student.forms import AccessibleFormMixin
from student.models import MentorRequest, Team

from .models import EvaluationScore, MentorEvaluation, MentoringSession

User = get_user_model()


class StyledFormMixin(AccessibleFormMixin):
    """Classes Bootstrap + attributs ARIA sur tous les champs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def style_fields(self):
        for field in self.fields.values():
            css = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            if isinstance(field.widget, forms.CheckboxInput):
                css = 'form-check-input'
            classes = field.widget.attrs.get('class', '').split()
            if css not in classes:
                classes.append(css)
            field.widget.attrs['class'] = ' '.join(classes)
            field.widget.attrs['aria-required'] = 'true' if field.required else 'false'


class TeamFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(label='Rechercher', required=False, max_length=100,
                        widget=forms.TextInput(attrs={'placeholder': 'Équipe, projet ou mot-clé…', 'type': 'search'}))
    category = forms.ChoiceField(label='Thématique', required=False)
    mine = forms.BooleanField(label='Mes équipes suivies uniquement', required=False)

    def __init__(self, *args, categories=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = [('', 'Toutes les thématiques')] + [(c, c) for c in categories]


class RequestFilterForm(StyledFormMixin, forms.Form):
    VIEW_CHOICES = [
        ('pending', "File d'attente"),
        ('mine', 'Mes tickets en cours'),
        ('resolved', 'Mes tickets résolus'),
    ]
    view = forms.ChoiceField(label='Affichage', choices=VIEW_CHOICES, required=False)
    urgency = forms.ChoiceField(label='Urgence', required=False,
                                choices=[('', 'Toutes les urgences')] + list(MentorRequest.Urgency.choices))


class ResolveRequestForm(StyledFormMixin, forms.Form):
    resolution_note = forms.CharField(
        label='Note de résolution', max_length=2000,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ce qui a été fait pour débloquer l’équipe…'}),
    )

    def clean_resolution_note(self):
        note = self.cleaned_data['resolution_note'].strip()
        if len(note) < 5:
            raise forms.ValidationError('Décrivez la résolution en quelques mots (5 caractères minimum).')
        return note


class TransferRequestForm(StyledFormMixin, forms.Form):
    mentor = forms.ModelChoiceField(label='Transférer à', queryset=User.objects.none(),
                                    empty_label='Choisir un mentor…')

    def __init__(self, *args, current_mentor=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = User.objects.filter(role='mentor', is_active=True).order_by('first_name', 'username')
        if current_mentor is not None:
            queryset = queryset.exclude(pk=current_mentor.pk)
        self.fields['mentor'].queryset = queryset
        self.fields['mentor'].label_from_instance = (
            lambda user: f"{user.get_full_name() or user.username}" + (f" — {user.specialty}" if user.specialty else '')
        )


DATETIME_FORMAT = '%Y-%m-%dT%H:%M'


class MentoringSessionForm(StyledFormMixin, forms.ModelForm):
    """Planification / modification d'une session par le mentor connecté."""

    class Meta:
        model = MentoringSession
        fields = ['team', 'help_request', 'topic', 'starts_at', 'ends_at', 'meeting_url', 'location', 'notes', 'status']
        labels = {
            'team': 'Équipe', 'help_request': "Demande d'aide liée (optionnel)", 'topic': 'Sujet',
            'starts_at': 'Début', 'ends_at': 'Fin', 'meeting_url': 'Lien visio', 'location': 'Lieu',
            'notes': 'Notes', 'status': 'Statut',
        }
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_FORMAT),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_FORMAT),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'meeting_url': forms.URLInput(attrs={'placeholder': 'https://meet.google.com/…'}),
            'location': forms.TextInput(attrs={'placeholder': 'Table 14, salle B…'}),
        }

    def __init__(self, *args, mentor, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.mentor = mentor
        self.fields['team'].queryset = Team.objects.filter(is_archived=False).order_by('name')
        self.fields['help_request'].queryset = (
            MentorRequest.objects.filter(mentor=mentor).exclude(status=MentorRequest.Status.PENDING)
            .select_related('team').order_by('-created_at')
        )
        self.fields['help_request'].label_from_instance = lambda r: f'#T-{r.pk:03} — {r.subject}'
        self.fields['help_request'].empty_label = 'Aucune'
        if self.instance.pk is None:
            # Une nouvelle session est forcément planifiée ; le statut se change ensuite.
            del self.fields['status']

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get('starts_at')
        if self.instance.pk is None and starts_at and starts_at < timezone.now() - timedelta(minutes=5):
            self.add_error('starts_at', 'Une nouvelle session ne peut pas commencer dans le passé.')
        if not cleaned.get('meeting_url') and not cleaned.get('location'):
            self.add_error('location', 'Indiquez un lien visio ou un lieu de rendez-vous.')
        return cleaned


class EvaluationForm(StyledFormMixin, forms.ModelForm):
    """Évaluation multi-critères : un champ note (+ commentaire) par critère actif de la grille."""

    class Meta:
        model = MentorEvaluation
        fields = ['pitch_readiness', 'general_comment']
        labels = {'pitch_readiness': 'Préparation au pitch', 'general_comment': 'Commentaire général'}
        widgets = {'general_comment': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, criteria, **kwargs):
        super().__init__(*args, **kwargs)
        self.criteria = list(criteria)
        existing = {s.criterion_id: s for s in self.instance.scores.all()} if self.instance.pk else {}
        for criterion in self.criteria:
            score = existing.get(criterion.pk)
            self.fields[f'score_{criterion.pk}'] = forms.DecimalField(
                label=f'{criterion.name} ({criterion.weight} %)', min_value=0, max_value=criterion.max_score,
                max_digits=4, decimal_places=1, initial=score.score if score else None,
                help_text=f'Note sur {criterion.max_score}',
                widget=forms.NumberInput(attrs={'step': '0.5', 'min': 0, 'max': criterion.max_score,
                                                'data-weight': criterion.weight, 'data-max': criterion.max_score,
                                                'class': 'js-score'}),
            )
            self.fields[f'comment_{criterion.pk}'] = forms.CharField(
                label=f'Commentaire — {criterion.name}', required=False, max_length=500,
                initial=score.comment if score else '',
                widget=forms.TextInput(attrs={'placeholder': 'Point fort, axe d’amélioration…'}),
            )
        self.style_fields()  # champs ajoutés dynamiquement : classes Bootstrap + ARIA

    def criterion_rows(self):
        return [(c, self[f'score_{c.pk}'], self[f'comment_{c.pk}']) for c in self.criteria]

    @transaction.atomic
    def save(self, commit=True):
        evaluation = super().save()
        for criterion in self.criteria:
            EvaluationScore.objects.update_or_create(
                evaluation=evaluation, criterion=criterion,
                defaults={'score': self.cleaned_data[f'score_{criterion.pk}'],
                          'comment': self.cleaned_data[f'comment_{criterion.pk}'].strip()},
            )
        return evaluation
