from django import forms
from django.contrib.auth import get_user_model

from student.forms import AccessibleFormMixin
from student.models import MentorRequest

User = get_user_model()


class StyledFormMixin(AccessibleFormMixin):
    """Classes Bootstrap + attributs ARIA sur tous les champs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            if isinstance(field.widget, forms.CheckboxInput):
                css = 'form-check-input'
            field.widget.attrs['class'] = f"{field.widget.attrs.get('class', '')} {css}".strip()


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
