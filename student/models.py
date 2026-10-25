from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
import zipfile

from accounts.storage import PrivateCVStorage


def validate_submission_zip(upload):
    if getattr(upload, '_committed', False):
        return
    if upload.size > 100 * 1024 * 1024:
        raise ValidationError('The ZIP archive must be no larger than 100 MB.')
    try:
        position = upload.tell()
        upload.seek(0)
        valid_zip = zipfile.is_zipfile(upload)
        upload.seek(position)
    except (AttributeError, OSError):
        valid_zip = False
    if not valid_zip:
        raise ValidationError('Upload a valid ZIP archive.')


class Hackathon(models.Model):
    name = models.CharField(max_length=160)
    edition = models.CharField(max_length=80, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.name} — {self.edition}'


class HackathonRegistration(models.Model):
    hackathon = models.ForeignKey(Hackathon, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hackathon_registrations')
    registered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['registered_at', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['hackathon', 'user'], name='unique_hackathon_registration'),
        ]

    def __str__(self):
        return f'{self.user} — {self.hackathon}'


class Milestone(models.Model):
    class Status(models.TextChoices):
        UPCOMING = 'upcoming', 'Upcoming'
        ACTIVE = 'active', 'In progress'
        DONE = 'done', 'Approved'

    hackathon = models.ForeignKey(Hackathon, on_delete=models.CASCADE, related_name='milestones')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField()
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPCOMING)

    class Meta:
        ordering = ['order', 'due_at']

    def __str__(self):
        return self.title


class Announcement(models.Model):
    class Audience(models.TextChoices):
        ALL = 'all', 'Everyone'
        STUDENTS = 'students', 'Students'
        MENTORS = 'mentors', 'Mentors'
        CAPTAINS = 'captains', 'Team captains'

    class Priority(models.TextChoices):
        INFO = 'info', 'Info'
        IMPORTANT = 'important', 'Important'
        URGENT = 'urgent', 'Urgent'

    hackathon = models.ForeignKey(Hackathon, on_delete=models.CASCADE, related_name='announcements')
    title = models.CharField(max_length=220)
    body = models.TextField(blank=True)
    author = models.CharField(max_length=120)
    category = models.CharField(max_length=80, blank=True)
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.ALL)
    priority = models.CharField(max_length=9, choices=Priority.choices, default=Priority.INFO)
    published_at = models.DateTimeField(default=timezone.now)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    is_draft = models.BooleanField(default=False)

    @property
    def is_scheduled(self):
        return not self.is_draft and bool(self.scheduled_at and self.scheduled_at > timezone.now())

    @property
    def status(self):
        if self.is_draft:
            return 'draft'
        if self.is_scheduled:
            return 'scheduled'
        return 'published'

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.title


class Team(models.Model):
    hackathon = models.ForeignKey(Hackathon, on_delete=models.CASCADE, related_name='teams')
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    table_number = models.CharField(max_length=80, blank=True)
    room = models.CharField(max_length=120, blank=True)
    max_members = models.PositiveSmallIntegerField(default=5)
    captain = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='captained_teams')
    is_archived = models.BooleanField(default=False)
    seeking_skill = models.CharField(max_length=180, blank=True)
    project_name = models.CharField(max_length=180, blank=True)
    project_pitch = models.TextField(blank=True)
    cover_image_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def member_count(self):
        return self.memberships.count()

    @property
    def places_left(self):
        return max(0, self.max_members - self.member_count)

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_memberships')
    role = models.CharField(max_length=120, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['team', 'user'], name='unique_team_member')]

    def __str__(self):
        return f'{self.user} — {self.team}'


class TeamLeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DECLINED = 'declined', 'Declined'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='leave_requests')
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_leave_requests')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='decided_team_leave_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['team', 'member'], condition=models.Q(status='pending'), name='unique_pending_team_leave_request',
        )]


class Sprint(models.Model):
    class Status(models.TextChoices):
        PLANNED = 'planned', 'Planned'
        ACTIVE = 'active', 'In progress'
        COMPLETED = 'completed', 'Completed'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='sprints')
    name = models.CharField(max_length=100)
    goal = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ['-starts_at']

    def __str__(self):
        return f'{self.name} — {self.team.name}'


class TeamInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invitations')
    invited_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='team_invitations')
    email = models.EmailField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_team_invitations')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Resource(models.Model):
    class Kind(models.TextChoices):
        GITHUB = 'github', 'GitHub'
        FIGMA = 'figma', 'Figma'
        DEMO = 'demo', 'Demo'
        DOCUMENT = 'document', 'Document'
        OTHER = 'other', 'Other'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=140)
    url = models.URLField(blank=True)
    document = models.FileField(
        upload_to='team_resources/', storage=PrivateCVStorage(), blank=True,
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = 'todo', 'To do'
        IN_PROGRESS = 'in_progress', 'In progress'
        REVIEW = 'review', 'In review'
        DONE = 'done', 'Done'

    class Priority(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='tasks')
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_student_tasks')
    deadline = models.DateTimeField(null=True, blank=True)
    repository = models.ForeignKey('repositories.Repository', on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_tasks')
    repository_branch = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AITaskJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        DONE = 'done', 'Done'
        FAILED = 'failed', 'Failed'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='ai_task_jobs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_task_jobs')
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name='ai_task_jobs')
    prompt = models.CharField(max_length=1000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(default=list, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    proposed_count = models.PositiveSmallIntegerField(default=0)
    accepted_count = models.PositiveSmallIntegerField(default=0)
    accepted_task_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        APPROVED = 'approved', 'Approved'
        REVISION = 'revision', 'Needs revision'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='submissions')
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name='submissions')
    project_name = models.CharField(max_length=180, blank=True)
    category = models.CharField(max_length=180, blank=True)
    description = models.TextField(blank=True)
    project_summary = models.TextField(blank=True, max_length=5000)
    github_url = models.URLField(blank=True)
    demo_url = models.URLField(blank=True)
    video_url = models.URLField(blank=True)
    repository = models.ForeignKey('repositories.Repository', on_delete=models.SET_NULL, null=True, blank=True, related_name='submissions')
    repository_commit = models.CharField(max_length=40, blank=True)
    file = models.FileField(
        upload_to='submissions/',
        blank=True,
        storage=PrivateCVStorage(),
        validators=[FileExtensionValidator(['zip']), validate_submission_zip],
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    feedback = models.TextField(blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'milestone'], name='unique_team_milestone_submission'),
        ]


class MentorRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        RESOLVED = 'resolved', 'Resolved'

    class Urgency(models.TextChoices):
        BLOCKING = 'blocking', 'Blocking'
        IMPORTANT = 'important', 'Important'
        NORMAL = 'normal', 'Advice'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentor_requests')
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='mentor_requests')
    mentor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_mentor_requests')
    subject = models.CharField(max_length=180)
    category = models.CharField(max_length=120)
    description = models.TextField()
    urgency = models.CharField(max_length=12, choices=Urgency.choices, default=Urgency.NORMAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    meeting_url = models.URLField(blank=True)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_notifications')
    message = models.CharField(max_length=240)
    title = models.CharField(max_length=120, blank=True)
    icon = models.CharField(max_length=60, default='bi-bell-fill')
    url = models.CharField(max_length=240, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']


class DirectMessage(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_direct_messages')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_direct_messages')
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'Message from {self.sender} to {self.recipient}'
