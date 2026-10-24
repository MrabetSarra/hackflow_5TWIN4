from django import forms
from django.utils import timezone

from student.models import Announcement, Hackathon


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ('title', 'category', 'audience', 'priority', 'body', 'scheduled_at')
        labels = {
            'title': "Titre de l'annonce",
            'category': 'Catégorie (facultatif)',
            'audience': 'Audience cible',
            'priority': "Niveau d'importance",
            'body': 'Contenu du message',
        }
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. : Changement de salle pour la présentation',
            }),
            'category': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. : Logistique',
                'maxlength': 80,
            }),
            'audience': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'body': forms.Textarea(attrs={
                'class': 'form-control announce-editor',
                'rows': 5,
                'maxlength': 5000,
                'placeholder': 'Détaillez les informations, consignes ou liens utiles…',
            }),
            'scheduled_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    scheduled_at = forms.DateTimeField(
        required=False, input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        label='Programmer la publication (facultatif)',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault('audience', Announcement.Audience.ALL)
        self.initial.setdefault('priority', Announcement.Priority.INFO)
        self.fields['body'].required = False
        self.fields['body'].max_length = 5000
        for field_name, field in self.fields.items():
            if self.errors.get(field_name):
                field.widget.attrs['class'] = (field.widget.attrs.get('class', '') + ' is-invalid').strip()

    def clean_body(self):
        body = self.cleaned_data.get('body', '').strip()
        if not body and self.data.get('submit_action') != 'draft':
            raise forms.ValidationError('Ajoutez le contenu de votre annonce.')
        return body

    def clean_scheduled_at(self):
        scheduled_at = self.cleaned_data.get('scheduled_at')
        unchanged_existing_value = self.instance.pk and scheduled_at == self.instance.scheduled_at
        if scheduled_at and scheduled_at <= timezone.now() and not unchanged_existing_value:
            raise forms.ValidationError('Choisissez une date et une heure dans le futur.')
        return scheduled_at


class HackathonForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
    )
    ends_at = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
    )

    class Meta:
        model = Hackathon
        fields = ('name', 'edition', 'starts_at', 'ends_at', 'location', 'is_active')
        labels = {
            'name': "Nom de l'événement",
            'edition': 'Édition',
            'starts_at': 'Début',
            'ends_at': 'Fin',
            'location': 'Lieu',
            'is_active': 'Ouvert aux inscriptions',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'edition': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Adresse ou lien en ligne'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get('starts_at')
        ends_at = cleaned.get('ends_at')
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error('ends_at', "La date de fin doit être postérieure à la date de début.")
        return cleaned
