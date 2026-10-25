from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from accounts.models import User
from student.models import Hackathon

from .models import (
    Challenge, FlashAnnouncement, HackathonProfile, HackathonResource,
    MentorFeedback,
    ScheduleItem, Track,
)

DT_FORMAT = '%Y-%m-%dT%H:%M'


class LenientDateTimeField(forms.DateTimeField):
    """Accepte les heures ambiguës ou inexistantes lors des changements d'heure (première occurrence retenue)."""

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime):
            result = value
        else:
            result = forms.fields.BaseTemporalField.to_python(self, value)
        if timezone.is_naive(result):
            result = result.replace(tzinfo=timezone.get_current_timezone())
        return result


def dt_field(label, required=True, help_text=''):
    return LenientDateTimeField(
        label=label, required=required, help_text=help_text, input_formats=[DT_FORMAT, '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DT_FORMAT),
        error_messages={'invalid': 'Saisissez une date et une heure valides.', 'required': 'Ce champ est obligatoire.'},
    )


class StyledFormMixin:
    """Applique les classes Bootstrap du projet et marque les champs invalides."""

    def _style(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = 'form-select'
            else:
                css = 'form-control'
            classes = set(widget.attrs.get('class', '').split()) - {'is-invalid'}
            classes.add(css)
            if self.is_bound and self._errors and self._errors.get(name):
                classes.add('is-invalid')
            widget.attrs['class'] = ' '.join(sorted(classes))
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('rows', 4)

    def full_clean(self):
        super().full_clean()
        self._style()


class BaseStyledForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


def _clean_text(value, label, min_len=0):
    value = ' '.join((value or '').split())
    if min_len and len(value) < min_len:
        raise forms.ValidationError(f'{label} doit contenir au moins {min_len} caractères.')
    return value


class HackathonForm(BaseStyledForm):
    name = forms.CharField(label='Titre', max_length=160)
    track_name = forms.CharField(
        label='Track', max_length=120,
        help_text='Thématique du hackathon (ex. Intelligence artificielle). Sert de filtre pour tous les utilisateurs.',
        widget=forms.TextInput(attrs={'list': 'track-suggestions', 'autocomplete': 'off'}),
    )
    edition = forms.CharField(label='Édition', max_length=80, required=False)
    location = forms.CharField(label='Lieu', max_length=180, required=False)
    starts_at = dt_field('Début')
    ends_at = dt_field('Fin')
    registration_deadline = dt_field("Date limite d'inscription", required=False)
    latitude = forms.FloatField(required=False, min_value=-90, max_value=90, widget=forms.HiddenInput)
    longitude = forms.FloatField(required=False, min_value=-180, max_value=180, widget=forms.HiddenInput)

    class Meta:
        model = HackathonProfile
        fields = (
            'short_description', 'description', 'banner',
            'registration_deadline', 'max_participants', 'rules', 'latitude', 'longitude',
        )

    field_order = [
        'name', 'edition', 'track_name', 'short_description', 'description', 'location',
        'banner', 'starts_at', 'ends_at', 'registration_deadline', 'max_participants', 'rules',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            event = self.instance.event
            for key in ('name', 'edition', 'location', 'starts_at', 'ends_at'):
                self.initial.setdefault(key, getattr(event, key))
            self.initial.setdefault('track_name', self.instance.track.name)
        self.fields['max_participants'].widget.attrs.update({'min': 1})
        self._style()

    def clean_name(self):
        return _clean_text(self.cleaned_data.get('name'), 'Le titre', 3)

    def clean_track_name(self):
        return _clean_text(self.cleaned_data.get('track_name'), 'Le track', 2)

    def clean(self):
        data = super().clean()
        starts, ends = data.get('starts_at'), data.get('ends_at')
        deadline = data.get('registration_deadline')
        if starts and ends and ends <= starts:
            self.add_error('ends_at', 'La fin doit être postérieure au début.')
        if starts and not self.instance.pk and starts < timezone.now():
            self.add_error('starts_at', 'La date de début doit être dans le futur.')
        if deadline and starts and deadline > starts:
            self.add_error('registration_deadline', 'La date limite doit précéder le début du hackathon.')
        if not data.get('location'):
            self.add_error('location', 'Indiquez le lieu du hackathon.')
        if (data.get('latitude') is None) != (data.get('longitude') is None):
            self.add_error('location', 'Choisissez un point complet sur la carte.')
        return data

    def save(self, commit=True, organizer=None):
        profile = super().save(commit=False)
        cd = self.cleaned_data
        if profile.pk:
            event = profile.event
        else:
            # is_active=False : n'interfère pas avec l'événement « courant » utilisé par les autres modules.
            event = Hackathon(is_active=False)
            profile.organizer = organizer
        event.name, event.edition, event.location = cd['name'], cd['edition'], cd['location']
        event.starts_at, event.ends_at = cd['starts_at'], cd['ends_at']
        event.save()
        profile.event = event
        profile.track = Track.objects.filter(name__iexact=cd['track_name']).first() or Track.objects.create(
            name=cd['track_name'])
        profile.save()
        return profile


class ChallengeScopedForm(BaseStyledForm):
    """Formulaire rattaché à un Challenge précis."""

    def __init__(self, *args, challenge=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.challenge = challenge or getattr(self.instance, 'challenge', None)
        self.hackathon = self.challenge.hackathon
        self.user = user
        self.setup()
        self._style()

    def setup(self):
        pass

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.challenge = self.challenge
        if commit:
            obj.save()
        return obj


class ChallengeForm(BaseStyledForm):
    class Meta:
        model = Challenge
        fields = (
            'title', 'short_description', 'description', 'objectives', 'problem_statement', 'constraints',
            'deliverables', 'guidelines', 'difficulty', 'technologies', 'reward',
        )

    def __init__(self, *args, hackathon=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hackathon = hackathon or self.instance.hackathon
        self._style()

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.hackathon = self.hackathon
        if commit:
            obj.save()
        return obj

    def clean_title(self):
        title = _clean_text(self.cleaned_data.get('title'), 'Le titre', 3)
        dup = Challenge.objects.filter(hackathon=self.hackathon, title__iexact=title).exclude(pk=self.instance.pk)
        if dup.exists():
            raise forms.ValidationError('Un challenge avec ce titre existe déjà dans ce hackathon.')
        return title


class ScheduleItemForm(ChallengeScopedForm):
    starts_at = dt_field('Début')
    ends_at = dt_field('Fin', required=False)

    class Meta:
        model = ScheduleItem
        fields = ('title', 'kind', 'starts_at', 'ends_at', 'location', 'description', 'is_key_step', 'mentor')

    def setup(self):
        self.fields['mentor'].queryset = User.objects.filter(role=User.Role.MENTOR, is_active=True)
        self.fields['mentor'].label_from_instance = lambda u: u.get_full_name() or u.username

    def clean_title(self):
        return _clean_text(self.cleaned_data.get('title'), 'Le titre', 3)

    def clean(self):
        data = super().clean()
        starts, ends = data.get('starts_at'), data.get('ends_at')
        if starts and ends and ends <= starts:
            self.add_error('ends_at', 'La fin doit être postérieure au début.')
        if starts and ends and self.hackathon and (
            starts < self.hackathon.starts_at - timedelta(days=1)
            or ends > self.hackathon.ends_at + timedelta(days=1)
        ):
            self.add_error('starts_at', "L'étape doit se situer pendant le hackathon (tolérance d'un jour).")
        if data.get('mentor') and data.get('kind') != ScheduleItem.Kind.MENTORING:
            self.add_error('mentor', 'Un mentor responsable ne se choisit que pour une permanence de mentorat.')
        return data


class FlashAnnouncementForm(ChallengeScopedForm):
    publish_at = dt_field('Date de publication')
    expires_at = dt_field("Date d'expiration", required=False)

    class Meta:
        model = FlashAnnouncement
        fields = ('message', 'level', 'publish_at', 'expires_at', 'is_published')
        widgets = {'message': forms.Textarea(attrs={'rows': 3, 'maxlength': 500})}

    def setup(self):
        self.initial.setdefault('publish_at', timezone.localtime().replace(second=0, microsecond=0))

    def clean_message(self):
        return _clean_text(self.cleaned_data.get('message'), 'Le message', 5)

    def clean(self):
        data = super().clean()
        if data.get('expires_at') and data.get('publish_at') and data['expires_at'] <= data['publish_at']:
            self.add_error('expires_at', "L'expiration doit être postérieure à la publication.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.author_id and self.user:
            obj.author = self.user
        if commit:
            obj.save()
        return obj


class ResourceForm(ChallengeScopedForm):
    class Meta:
        model = HackathonResource
        fields = ('title', 'category', 'description', 'url', 'file', 'is_published')

    def clean_title(self):
        return _clean_text(self.cleaned_data.get('title'), 'Le titre', 3)

    def clean(self):
        data = super().clean()
        if not data.get('url') and not data.get('file'):
            self.add_error('url', 'Fournissez un lien ou un fichier.')
        return data


class MentorFeedbackForm(BaseStyledForm):
    class Meta:
        model = MentorFeedback
        fields = ('rating', 'review', 'ideas')
        widgets = {
            'rating': forms.Select(choices=[('', 'Sans note')] + [(n, f'{n} / 5') for n in range(1, 6)]),
            'review': forms.Textarea(attrs={'rows': 5, 'maxlength': 5000, 'placeholder': 'Votre avis sur ce hackathon ou ce challenge…'}),
            'ideas': forms.Textarea(attrs={'rows': 4, 'maxlength': 3000, 'placeholder': 'Vos idées et suggestions…'}),
        }

    def clean(self):
        data = super().clean()
        if not (data.get('review', '').strip() or data.get('ideas', '').strip()):
            raise forms.ValidationError('Rédigez un avis ou une idée avant l’envoi.')
        return data
