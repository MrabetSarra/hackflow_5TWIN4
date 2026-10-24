from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from accounts.models import validate_cv_size
from accounts.storage import PrivateCVStorage


def validate_application_cv(upload):
    if getattr(upload, '_committed', False):
        return
    try:
        position = upload.tell()
        upload.seek(0)
        signature = upload.read(5)
        upload.seek(position)
    except (AttributeError, OSError):
        signature = b''
    if signature != b'%PDF-':
        raise ValidationError('Upload a valid PDF document.')


class Opportunity(models.Model):
    class Type(models.TextChoices):
        JOB = 'job', 'Job'
        INTERNSHIP = 'internship', 'Internship'
        APPRENTICESHIP = 'apprenticeship', 'Apprenticeship / work-study'
        ENTRY_LEVEL = 'entry_level', 'Entry-level'
        GRADUATE = 'graduate', 'Graduate'
        OTHER = 'other', 'Other'

    class WorkMode(models.TextChoices):
        ONSITE = 'onsite', 'On-site'
        HYBRID = 'hybrid', 'Hybrid'
        REMOTE = 'remote', 'Remote'
        UNSPECIFIED = 'unspecified', 'Not specified'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        REVIEW = 'review', 'Pending review'
        PUBLISHED = 'published', 'Published'
        REJECTED = 'rejected', 'Rejected'
        ARCHIVED = 'archived', 'Archived'

    title = models.CharField(max_length=240)
    company = models.CharField(max_length=180)
    description = models.TextField()
    opportunity_type = models.CharField(max_length=20, choices=Type.choices, default=Type.OTHER)
    education = models.CharField(max_length=180, blank=True)
    experience = models.CharField(max_length=180, blank=True)
    location = models.CharField(max_length=180, blank=True)
    work_mode = models.CharField(max_length=15, choices=WorkMode.choices, default=WorkMode.UNSPECIFIED)
    languages = models.JSONField(default=list, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    salary = models.CharField(max_length=120, blank=True)
    application_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    internal_application = models.BooleanField(default=False)
    moderation_note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_opportunities')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-publication_date', '-created_at']
    @property
    def is_expired(self):
        return bool(self.deadline and self.deadline < timezone.localdate())

    @property
    def is_open(self):
        return self.status == self.Status.PUBLISHED and not self.is_expired

    def __str__(self):
        return f'{self.title} — {self.company}'


class OpportunitySkill(models.Model):
    class Kind(models.TextChoices):
        REQUIRED = 'required', 'Required'
        PREFERRED = 'preferred', 'Preferred'

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='skills')
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REQUIRED)
    evidence = models.CharField(max_length=300, blank=True)
    verified = models.BooleanField(default=False)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=1, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        ordering = ['kind', 'name']
        constraints = [models.UniqueConstraint(fields=['opportunity', 'name', 'kind'], name='career_skill_uniq')]


class CareerRequirement(models.Model):
    class Kind(models.TextChoices):
        EDUCATION = 'education', 'Education / qualification'
        EXPERIENCE = 'experience', 'Experience'
        LANGUAGE = 'language', 'Language'
        PROJECT = 'project', 'Project experience'
        LOCATION = 'location', 'Location / work arrangement'
        OTHER = 'other', 'Other eligibility'

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='requirements')
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    mandatory = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['kind', 'name']


class StudentCVAnalysis(models.Model):
    class Status(models.TextChoices):
        READY = 'ready', 'Ready'
        UNREADABLE = 'unreadable', 'Unreadable PDF'
        EMPTY = 'empty', 'No extractable text'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_cv_analysis')
    cv_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices)
    structured_data = models.JSONField(default=dict, blank=True)
    analyzed_at = models.DateTimeField(auto_now=True)


class CareerMatchCache(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_match_cache')
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='match_cache')
    cv_digest = models.CharField(max_length=64)
    profile_digest = models.CharField(max_length=64)
    opportunity_updated_at = models.DateTimeField()
    result = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'opportunity'], name='career_match_cache_unique')]


class SavedOpportunity(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_career_opportunities')
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='saves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'opportunity'], name='career_saved_uniq')]


class CareerApplication(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        INTENDED = 'intended', 'Intention to apply'
        SUBMITTED = 'submitted', 'Submitted'
        REVIEW = 'review', 'Under review'
        INTERVIEW = 'interview', 'Interview'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        WITHDRAWN = 'withdrawn', 'Withdrawn'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_applications')
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INTENDED)
    cv = models.FileField(upload_to='career_applications/', storage=PrivateCVStorage(), blank=True, validators=[FileExtensionValidator(['pdf']), validate_cv_size, validate_application_cv])
    portfolio_url = models.URLField(blank=True)
    note = models.CharField(max_length=500, blank=True)
    interview_at = models.DateTimeField(null=True, blank=True)
    organizer_update = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['user', 'opportunity'], name='career_unique_user_application')]


class ApplicationHistory(models.Model):
    application = models.ForeignKey(CareerApplication, on_delete=models.CASCADE, related_name='history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    old_status = models.CharField(max_length=12, choices=CareerApplication.Status.choices, blank=True)
    new_status = models.CharField(max_length=12, choices=CareerApplication.Status.choices)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
