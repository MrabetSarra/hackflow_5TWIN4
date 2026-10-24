"""
workshops/forms.py
==================
WorkshopForm     — Création / édition d'un atelier (organisateur)
WorkshopFilterForm — Filtrage du catalogue (tous rôles)
RatingForm       — Notation 1-5 + commentaire (étudiant)
"""

import json

from django import forms
from django.utils import timezone

from .models import Booking, Workshop


# ---------------------------------------------------------------------------
# Widgets Bootstrap helpers
# ---------------------------------------------------------------------------

class _BootstrapMixin:
    """Applique les classes Bootstrap 5 à tous les champs du formulaire."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get('class', '')
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs['class'] = (existing + ' form-select').strip()
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = (existing + ' form-check-input').strip()
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = (existing + ' form-control').strip()
                widget.attrs.setdefault('rows', 4)
            elif isinstance(widget, forms.DateTimeInput):
                widget.attrs['class'] = (existing + ' form-control').strip()
            else:
                widget.attrs['class'] = (existing + ' form-control').strip()


# ---------------------------------------------------------------------------
# WorkshopForm
# ---------------------------------------------------------------------------

class WorkshopForm(_BootstrapMixin, forms.ModelForm):
    """
    Formulaire de création / édition d'un atelier.

    Le champ topic_tags est exposé comme un champ texte (virgules)
    et converti en JSON list lors de la validation.
    """

    topic_tags_raw = forms.CharField(
        label='Tags thématiques',
        required=False,
        help_text='Séparés par des virgules : AWS, Docker, DevOps',
        widget=forms.TextInput(attrs={
            'placeholder': 'ex : Python, Machine Learning, API',
        }),
    )

    class Meta:
        model  = Workshop
        fields = [
            'title', 'description',
            'speaker_name', 'speaker_company',
            'topic_tags_raw',       # champ virtuel → topic_tags
            'level', 'mode',
            'room', 'meeting_url',
            'replay_url', 'replay_duration', 'available_until',
            'starts_at', 'ends_at',
            'capacity', 'is_open',
            'cover_image',
        ]
        exclude = ['topic_tags', 'slug', 'created_by', 'created_at']
        widgets = {
            'starts_at':      forms.DateTimeInput(
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ends_at':        forms.DateTimeInput(
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'available_until': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'description':    forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pré-remplir topic_tags_raw depuis l'instance existante
        if self.instance and self.instance.pk:
            tags = self.instance.topic_tags or []
            self.fields['topic_tags_raw'].initial = ', '.join(tags)
        # Champs optionnels selon le mode
        self.fields['room'].required           = False
        self.fields['meeting_url'].required    = False
        self.fields['replay_url'].required     = False
        self.fields['replay_duration'].required = False
        self.fields['available_until'].required = False

    # ------------------------------------------------------------------
    # Validation globale
    # ------------------------------------------------------------------

    def clean(self):
        cleaned = super().clean()
        starts  = cleaned.get('starts_at')
        ends    = cleaned.get('ends_at')
        mode    = cleaned.get('mode')
        room    = cleaned.get('room', '').strip()
        meeting = cleaned.get('meeting_url', '').strip()
        replay  = cleaned.get('replay_url', '').strip()

        # 1. Créneau cohérent
        if starts and ends and ends <= starts:
            self.add_error('ends_at',
                           'La date de fin doit être postérieure à la date de début.')

        # 2. Contraintes selon le mode
        if mode == Workshop.Mode.ONSITE and not room:
            self.add_error('room',
                           'Une salle est obligatoire pour un atelier présentiel.')

        if mode == Workshop.Mode.ONLINE and not meeting:
            self.add_error('meeting_url',
                           'Un lien de réunion est obligatoire pour un atelier live.')

        if mode == Workshop.Mode.RECORDED and not replay:
            self.add_error('replay_url',
                           'Une URL de replay est obligatoire pour une vidéo enregistrée.')

        # 3. Capacité : replay → 0 (illimité) recommandé
        capacity = cleaned.get('capacity', 0)
        if mode == Workshop.Mode.RECORDED and capacity > 0:
            # On informe mais on n'bloque pas
            pass

        return cleaned

    def clean_topic_tags_raw(self):
        raw = self.cleaned_data.get('topic_tags_raw', '')
        if not raw.strip():
            return []
        return [t.strip() for t in raw.split(',') if t.strip()]

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Réinjecte topic_tags depuis le champ virtuel
        instance.topic_tags = self.cleaned_data.get('topic_tags_raw', [])
        if commit:
            instance.save()
        return instance


# ---------------------------------------------------------------------------
# WorkshopFilterForm
# ---------------------------------------------------------------------------

class WorkshopFilterForm(forms.Form):
    """Filtres du catalogue d'ateliers."""

    q = forms.CharField(
        label='Recherche',
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Titre, intervenant, tag…',
            'class': 'form-control',
        }),
    )
    mode = forms.ChoiceField(
        label='Mode',
        required=False,
        choices=[('', 'Tous les modes')] + Workshop.Mode.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    level = forms.ChoiceField(
        label='Niveau',
        required=False,
        choices=[('', 'Tous niveaux')] + Workshop.Level.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    only_open = forms.BooleanField(
        label='Inscriptions ouvertes uniquement',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    sort = forms.ChoiceField(
        label='Trier par',
        required=False,
        choices=[
            ('date',   'Date (plus proche)'),
            ('-date',  'Date (plus loin)'),
            ('fill',   'Places restantes'),
            ('rating', 'Meilleures notes'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


# ---------------------------------------------------------------------------
# RatingForm
# ---------------------------------------------------------------------------

STAR_CHOICES = [
    (1, '⭐ 1 — Décevant'),
    (2, '⭐⭐ 2 — Passable'),
    (3, '⭐⭐⭐ 3 — Bien'),
    (4, '⭐⭐⭐⭐ 4 — Très bien'),
    (5, '⭐⭐⭐⭐⭐ 5 — Excellent'),
]


class RatingForm(_BootstrapMixin, forms.ModelForm):
    """Permet à un étudiant de noter et commenter un atelier suivi."""

    class Meta:
        model   = Booking
        fields  = ['rating', 'comment']
        widgets = {
            'rating':  forms.RadioSelect(choices=STAR_CHOICES),
            'comment': forms.Textarea(attrs={'rows': 3,
                                             'placeholder': 'Votre avis (facultatif)…'}),
        }

    def clean_rating(self):
        rating = self.cleaned_data.get('rating')
        if rating is not None and not (1 <= rating <= 5):
            raise forms.ValidationError('La note doit être comprise entre 1 et 5.')
        return rating
