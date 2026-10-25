from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

from .models import validate_cv_size, validate_profile_photo_size


class AccessibleFormMixin:
    """Expose required state consistently to assistive technology."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['aria-required'] = 'true' if field.required else 'false'

    def full_clean(self):
        super().full_clean()
        for name, field in self.fields.items():
            if self.errors.get(name):
                field.widget.attrs['aria-invalid'] = 'true'
                field.widget.attrs['aria-describedby'] = f'{field.widget.attrs.get("id", f"id_{name}")}_errors'


class EmailOrUsernameAuthenticationForm(AccessibleFormMixin, AuthenticationForm):
    """Authenticate with either the account username or its unique email."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].max_length = 254
        self.fields['username'].label = _('Username or email address')
        self.fields['username'].widget.attrs.update({
            'class': 'form-control border-start-0 ps-0',
            'placeholder': 'name@university.edu',
            'autocomplete': 'username',
            'autofocus': True,
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control border-start-0 ps-0',
            'placeholder': _('Your password'),
            'autocomplete': 'current-password',
        })

    def clean(self):
        identifier = self.cleaned_data.get('username')
        if identifier and '@' in identifier:
            users = get_user_model()._default_manager.filter(email__iexact=identifier)
            if users.count() != 1:
                raise forms.ValidationError(
                    self.error_messages['invalid_login'],
                    code='invalid_login',
                    params={'username': self.username_field.verbose_name},
                )
            self.cleaned_data['username'] = users.get().get_username()
        return super().clean()


class AccountRegistrationForm(AccessibleFormMixin, forms.Form):
    first_name = forms.CharField(max_length=150, label=_('First name'))
    last_name = forms.CharField(max_length=150, label=_('Last name'))
    username = forms.CharField(max_length=150, label=_('Username'))
    email = forms.EmailField(max_length=254, label=_('Email address'))
    school = forms.CharField(max_length=150, label=_('School / organization'))
    study_level = forms.ChoiceField(
        choices=[
            ('', _('Choose a study level')),
            ('Licence 1 ou 2', _('Bachelor 1 or 2')),
            ('Licence 3 / BUT', _('Bachelor 3 / University Bachelor of Technology')),
            ('Master 1', _('Master 1')),
            ('Master 2 / Cycle Ingénieur', _('Master 2 / Engineering degree')),
            ('Autre cursus', _('Other')),
        ],
        label=_('Study level'),
        required=False,
    )
    specialty = forms.CharField(max_length=150, label=_('Specialty'), required=False)
    skills = forms.MultipleChoiceField(label=_('Skills'), required=False, widget=forms.CheckboxSelectMultiple)
    bio = forms.CharField(label=_('About me'), required=False, widget=forms.Textarea(attrs={'rows': 3}))
    github_url = forms.URLField(max_length=200, label=_('GitHub profile'), required=False)
    linkedin_url = forms.URLField(max_length=200, label=_('LinkedIn profile'), required=False)
    password1 = forms.CharField(label=_('Password'), strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label=_('Confirm password'), strip=False, widget=forms.PasswordInput)

    SKILL_CHOICES = [
        ('Python / Django', 'Python / Django'), ('React / TypeScript', 'React / TypeScript'),
        ('Vue.js', 'Vue.js'), ('FastAPI', 'FastAPI'), ('UI/UX & Figma', 'UI/UX & Figma'),
        ('IA & Machine Learning', 'IA & Machine Learning'), ('DevOps & Docker', 'DevOps & Docker'),
        ('Flutter / Mobile', 'Flutter / Mobile'), ('PostgreSQL', 'PostgreSQL'),
        ('Pitch & Business Model', 'Pitch & Business Model'),
    ]

    def __init__(self, *args, role, **kwargs):
        if role not in ('student', 'mentor'):
            raise ValueError('Registration is available for students and mentors only.')
        self.role = role
        super().__init__(*args, **kwargs)
        if role == 'student':
            labels = {
                'first_name': 'First name', 'last_name': 'Last name', 'username': 'Username',
                'email': _('Email address'), 'school': _('School / organization'), 'study_level': _('Study level'),
                'skills': _('Skills'), 'bio': _('About me'), 'github_url': _('GitHub profile'),
                'linkedin_url': _('LinkedIn profile'), 'password1': _('Password'), 'password2': _('Confirm password'),
            }
            for name, label in labels.items():
                if name in self.fields:
                    self.fields[name].label = label
            level_labels = {
                '': _('Choose a study level'), 'Licence 1 ou 2': _('Bachelor 1 or 2'),
                'Licence 3 / BUT': _('Bachelor 3 / University Bachelor of Technology'),
                'Master 1': _('Master 1'), 'Master 2 / Cycle Ingénieur': _('Master 2 / Engineering degree'),
                'Autre cursus': _('Other'),
            }
            self.fields['study_level'].choices = [
                (value, level_labels.get(value, label))
                for value, label in self.fields['study_level'].choices
            ]
            self.fields['study_level'].choices = [
                ('', _('Choose a study level')), *self.fields['study_level'].choices[1:]
            ]
            self.fields['skills'].choices = [
                (value, _(value.replace('IA &', 'AI &'))) for value, _label in self.SKILL_CHOICES
            ]
            self.fields.pop('specialty')
            self.fields['study_level'].required = True
            self.fields['skills'].choices = [
                (value, _(value.replace('IA &', 'AI &'))) for value, _label in self.SKILL_CHOICES
            ]
            self.fields['skills'].required = True
        else:
            self.fields.pop('study_level')
            self.fields.pop('skills')
            self.fields['specialty'].required = True

        for name, field in self.fields.items():
            if name == 'skills':
                continue
            css_class = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            field.widget.attrs.setdefault('class', css_class)
            field.widget.attrs.setdefault('autocomplete', 'new-password' if name.startswith('password') else 'on')

    def clean_username(self):
        username = self.cleaned_data['username']
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_('This username is already taken.'))
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_('An account already uses this email address.'))
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'The passwords do not match.' if self.role == 'student' else 'Les deux mots de passe ne correspondent pas.')
        elif password1:
            user = get_user_model()(
                username=cleaned.get('username', ''),
                email=cleaned.get('email', ''),
                first_name=cleaned.get('first_name', ''),
                last_name=cleaned.get('last_name', ''),
            )
            try:
                validate_password(password1, user=user)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned

    def save(self):
        User = get_user_model()
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
            school=self.cleaned_data['school'],
            bio=self.cleaned_data['bio'],
            github_url=self.cleaned_data['github_url'],
            linkedin_url=self.cleaned_data['linkedin_url'],
            role=self.role,
            study_level=self.cleaned_data.get('study_level', ''),
            specialty=self.cleaned_data.get('specialty', ''),
            skills=self.cleaned_data.get('skills', []),
        )
        return user


class PasswordResetRequestForm(AccessibleFormMixin, forms.Form):
    email = forms.EmailField(label='Email address', max_length=254)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'name@example.com',
            'autocomplete': 'email',
        })


class PasswordResetVerifyForm(AccessibleFormMixin, forms.Form):
    email = forms.EmailField(label='Email address', max_length=254)
    code = forms.RegexField(regex=r'^\d{6}$', label='Verification code', error_messages={
        'invalid': 'Enter the 6-digit code sent to your email.',
    })
    new_password1 = forms.CharField(label='New password', strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label='Confirm password', strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({'class': 'form-control', 'autocomplete': 'email'})
        self.fields['code'].widget.attrs.update({
            'class': 'form-control text-center fw-bold letter-spacing-code',
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'maxlength': '6',
        })
        for name in ('new_password1', 'new_password2'):
            self.fields[name].widget.attrs.update({'class': 'form-control', 'autocomplete': 'new-password'})

    def clean(self):
        cleaned = super().clean()
        first = cleaned.get('new_password1')
        second = cleaned.get('new_password2')
        if first and second and first != second:
            self.add_error('new_password2', _('The two passwords do not match.'))
        return cleaned


class ProfileAssetsForm(AccessibleFormMixin, forms.ModelForm):
    profile_photo = forms.ImageField(
        required=False,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']), validate_profile_photo_size],
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/png,image/webp'}),
    )
    cv = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(['pdf']), validate_cv_size],
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'application/pdf,.pdf'}),
    )

    class Meta:
        model = get_user_model()
        fields = ('profile_photo', 'cv')
        labels = {
            'profile_photo': _('Profile photo'),
            'cv': _('CV (PDF)'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.role == 'student':
            self.fields['profile_photo'].label = _('Profile photo')
            self.fields['cv'].label = _('CV (PDF)')

    def clean_cv(self):
        uploaded_file = self.cleaned_data.get('cv')
        if uploaded_file:
            signature = uploaded_file.read(5)
            uploaded_file.seek(0)
            if signature != b'%PDF-':
                message = _('The selected file does not appear to be a valid PDF.')
                raise forms.ValidationError(message)
        return uploaded_file


class ProfileDetailsForm(AccessibleFormMixin, forms.ModelForm):
    """Editable account details with uniqueness and role-specific validation."""

    study_level = forms.ChoiceField(
        choices=[('', _('Choose a study level'))], required=False,
        label=_('Study level'), widget=forms.Select(attrs={'class': 'form-select'}),
    )
    skills = forms.MultipleChoiceField(
        choices=[], required=False, label=_('Skills'),
        widget=forms.CheckboxSelectMultiple,
    )
    preferred_roles = forms.MultipleChoiceField(
        choices=[('developer', _('Development')), ('designer', _('Design / UX')), ('business', _('Business / Pitch')), ('product', _('Product')), ('data_ai', _('Data / AI'))],
        required=False, label=_('Preferred roles'), widget=forms.CheckboxSelectMultiple,
    )
    availability_windows = forms.MultipleChoiceField(
        choices=[('weekday_day', _('Weekdays during the day')), ('weekday_evening', _('Weekday evenings')), ('weekend', _('Weekends')), ('flexible', _('Flexible'))],
        required=False, label=_('Availability during the hackathon'), widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = get_user_model()
        fields = (
            'first_name', 'last_name', 'username', 'email', 'school', 'study_level',
            'specialty', 'skills', 'preferred_roles', 'preferred_categories', 'availability_windows',
            'bio', 'github_url', 'linkedin_url',
        )
        labels = {
            'first_name': _('First name'), 'last_name': _('Last name'), 'username': _('Username'),
            'email': _('Email address'), 'school': _('School / organization'),
            'study_level': _('Study level'), 'specialty': _('Specialty'),
            'skills': _('Skills'), 'bio': _('About me'),
            'github_url': _('GitHub profile'), 'linkedin_url': _('LinkedIn profile'),
            'preferred_roles': _('Preferred roles'), 'preferred_categories': _('Preferred project themes'),
            'availability_windows': _('Availability during the hackathon'),
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 4}),
        }

    SKILL_CHOICES = AccountRegistrationForm.SKILL_CHOICES
    STUDY_LEVEL_CHOICES = [
        ('Licence 1 ou 2', _('Bachelor 1 or 2')), ('Licence 3 / BUT', _('Bachelor 3 / University Bachelor of Technology')),
        ('Master 1', _('Master 1')), ('Master 2 / Cycle Ingénieur', _('Master 2 / Engineering degree')),
        ('Autre cursus', _('Other')),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['preferred_categories'].help_text = _('Separate multiple themes with commas (for example: health, climate, education).')
        self.fields['availability_windows'].help_text = _('Unspecified availability is treated as unknown.')
        self.fields['skills'].choices = self.SKILL_CHOICES
        self.fields['study_level'].choices = [('', _('Choose a study level')), *self.STUDY_LEVEL_CHOICES]
        self.initial['skills'] = self.instance.skills or []
        self.initial['preferred_roles'] = self.instance.preferred_roles or []
        self.initial['availability_windows'] = self.instance.availability_windows or []
        self.fields['skills'].required = False
        for name, field in self.fields.items():
            if name in ('skills', 'preferred_roles', 'availability_windows'):
                continue
            field.widget.attrs.setdefault('class', 'form-select' if isinstance(field.widget, forms.Select) else 'form-control')
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['school'].required = True
        self.fields['username'].widget.attrs.update({'minlength': 3, 'autocomplete': 'username'})
        self.fields['email'].widget.attrs.update({'autocomplete': 'email'})
        if self.instance.role == 'student':
            student_labels = {
                'first_name': _('First name'), 'last_name': _('Last name'), 'username': _('Username'),
                'email': _('Email address'), 'school': _('School / organization'),
                'study_level': _('Study level'), 'skills': _('Skills'), 'bio': _('About me'),
                'github_url': _('GitHub profile'), 'linkedin_url': _('LinkedIn profile'),
                'preferred_roles': _('Preferred roles'), 'preferred_categories': _('Preferred project themes'),
                'availability_windows': _('Availability during the hackathon'),
            }
            for name, label in student_labels.items():
                if name in self.fields:
                    self.fields[name].label = label
            level_labels = {
                'Licence 1 ou 2': _('Bachelor 1 or 2'), 'Licence 3 / BUT': _('Bachelor 3 / University Bachelor of Technology'),
                'Master 1': _('Master 1'), 'Master 2 / Cycle Ingénieur': _('Master 2 / Engineering degree'),
                'Autre cursus': _('Other'),
            }
            self.fields['study_level'].choices = [
                (value, level_labels.get(value, label))
                for value, label in self.fields['study_level'].choices
            ]
            self.fields['study_level'].choices = [
                ('', _('Choose a study level')), *self.fields['study_level'].choices[1:]
            ]
            self.fields['study_level'].required = True
            self.fields.pop('specialty')
        elif self.instance.role == 'mentor':
            self.fields.pop('preferred_roles')
            self.fields.pop('preferred_categories')
            self.fields.pop('availability_windows')
            self.fields['specialty'].required = True
            self.fields.pop('study_level')
            self.fields.pop('skills')
        else:
            self.fields.pop('preferred_roles')
            self.fields.pop('preferred_categories')
            self.fields.pop('availability_windows')
            self.fields.pop('study_level')
            self.fields.pop('specialty')
            self.fields.pop('skills')

    def save(self, commit=True):
        user = super().save(commit=False)
        if 'skills' in self.cleaned_data:
            user.skills = self.cleaned_data['skills']
        if 'preferred_roles' in self.cleaned_data:
            user.preferred_roles = self.cleaned_data['preferred_roles']
        if 'availability_windows' in self.cleaned_data:
            user.availability_windows = self.cleaned_data['availability_windows']
        if commit:
            user.save()
            self.save_m2m()
        return user

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        users = get_user_model().objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if users.exists():
            message = 'This username is already taken.' if self.instance.role == 'student' else "Ce nom d'utilisateur est déjà utilisé."
            raise forms.ValidationError(message)
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        users = get_user_model().objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if users.exists():
            message = 'This email address is already in use.' if self.instance.role == 'student' else 'Cette adresse e-mail est déjà utilisée.'
            raise forms.ValidationError(message)
        return email

    def clean_skills(self):
        skills = self.cleaned_data.get('skills', [])
        allowed = {value for value, _label in self.SKILL_CHOICES}
        invalid = set(skills) - allowed
        if invalid:
            message = 'Select skills from the available list.' if self.instance.role == 'student' else 'Sélectionnez des compétences proposées dans la liste.'
            raise forms.ValidationError(message)
        return skills


class TwoFactorVerifyForm(AccessibleFormMixin, forms.Form):
    code = forms.CharField(
        label='Code de vérification',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center font-monospace tracking-wider',
            'placeholder': '123456 ou code de secours',
            'autocomplete': 'one-time-code',
            'autofocus': True,
        }),
        help_text="Entrez le code à 6 chiffres de votre application d'authentification ou un code de secours.",
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip().replace(' ', '')
        if not code:
            raise forms.ValidationError('Veuillez entrer un code.')
        return code


class TwoFactorSetupForm(AccessibleFormMixin, forms.Form):
    code = forms.CharField(
        label='Code de confirmation (6 chiffres)',
        max_length=8,
        min_length=6,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center font-monospace',
            'placeholder': '123456',
            'autocomplete': 'one-time-code',
            'autofocus': True,
        }),
        help_text="Entrez le code affiché sur votre application pour confirmer la configuration.",
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip().replace(' ', '')
        if not code.isdigit() or len(code) != 6:
            raise forms.ValidationError('Le code doit comporter exactement 6 chiffres.')
        return code


class TwoFactorDisableForm(AccessibleFormMixin, forms.Form):
    password = forms.CharField(
        label='Mot de passe actuel',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre mot de passe pour confirmer',
            'autocomplete': 'current-password',
            'autofocus': True,
        }),
        help_text="Par mesure de sécurité, veuillez confirmer votre mot de passe pour désactiver le 2FA.",
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.user.check_password(password):
            raise forms.ValidationError('Mot de passe incorrect.')
        return password


class TwoFactorRegenerateBackupCodesForm(AccessibleFormMixin, forms.Form):
    password = forms.CharField(
        label='Mot de passe actuel',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Entrez votre mot de passe pour confirmer',
            'autocomplete': 'current-password',
            'autofocus': True,
        }),
        help_text="Confirmez votre mot de passe pour générer un nouveau jeu de codes de secours.",
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.user.check_password(password):
            raise forms.ValidationError('Mot de passe incorrect.')
        return password
