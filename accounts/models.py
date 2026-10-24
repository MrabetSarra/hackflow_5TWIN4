from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from .storage import PrivateCVStorage


def validate_profile_photo_size(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError('La photo ne doit pas dépasser 5 Mo.')


def validate_cv_size(upload):
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError('Le CV ne doit pas dépasser 10 Mo.')


class User(AbstractUser):
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')

    class Role(models.TextChoices):
        STUDENT = "student", "Étudiant"
        MENTOR = "mentor", "Mentor"
        ADMIN = "admin", "Administrateur"
        ORGANIZATION = "organization", "Organization"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    bio = models.TextField(blank=True)
    school = models.CharField(max_length=150, blank=True)
    study_level = models.CharField(max_length=100, blank=True)
    skills = models.JSONField(default=list, blank=True)
    specialty = models.CharField(max_length=150, blank=True)
    profile_photo = models.ImageField(
        upload_to='profile_photos/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']), validate_profile_photo_size],
    )
    cv = models.FileField(
        upload_to='resumes/',
        blank=True,
        null=True,
        storage=PrivateCVStorage(),
        validators=[FileExtensionValidator(['pdf']), validate_cv_size],
    )
    github_url = models.URLField(max_length=200, blank=True)
    linkedin_url = models.URLField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Django's createsuperuser command does not know about HackFlow roles.
        # A new superuser gets the model's default role (student), so promote
        # that default to the matching HackFlow administrator role.
        if self.is_superuser and self.role == self.Role.STUDENT:
            self.role = self.Role.ADMIN
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'role'}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes')
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now() and self.attempts < 5
