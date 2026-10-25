from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils import timezone


class Repository(models.Model):
    class Provider(models.TextChoices):
        GITHUB = 'github', 'GitHub'

    team = models.ForeignKey('student.Team', on_delete=models.CASCADE, related_name='repositories')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=110)
    description = models.TextField(blank=True, max_length=1000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_repositories')
    default_branch = models.CharField(max_length=100, default='main')
    protected_branches = models.JSONField(default=list, blank=True)
    remote_provider = models.CharField(max_length=20, choices=Provider.choices, blank=True)
    remote_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    remote_node_id = models.CharField(max_length=100, blank=True)
    remote_owner = models.CharField(max_length=100, blank=True)
    remote_name = models.CharField(max_length=100, blank=True)
    remote_url = models.URLField(max_length=500, blank=True)
    clone_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['team', 'slug'], name='unique_team_repository_slug')]

    def __str__(self):
        return f'{self.team.name} / {self.name}'

    @property
    def path(self):
        from django.conf import settings
        return settings.REPOS_ROOT / str(self.team_id) / f'{self.slug}.git'

    def is_protected(self, branch):
        return branch == self.default_branch or branch in (self.protected_branches or [])


class MergeRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        MERGED = 'merged', 'Merged'
        CLOSED = 'closed', 'Closed'

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='merge_requests')
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=5000)
    source_branch = models.CharField(max_length=100)
    target_branch = models.CharField(max_length=100)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='authored_merge_requests')
    reviewers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='review_merge_requests')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    merged_commit = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-created_at']


class MergeRequestComment(models.Model):
    merge_request = models.ForeignKey(MergeRequest, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class RepoActivity(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='activities')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=32)
    message = models.CharField(max_length=240)
    branch = models.CharField(max_length=100, blank=True)
    commit_hash = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class MergeSession(models.Model):
    merge_request = models.OneToOneField(MergeRequest, on_delete=models.CASCADE, related_name='merge_session')
    target_tip = models.CharField(max_length=40)
    source_tip = models.CharField(max_length=40)
    conflicts = models.JSONField(default=dict)
    resolved = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AIUsageLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='repository_ai_usage')
    feature = models.CharField(max_length=40)
    token_estimate = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    provider = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=120, blank=True)
    # A retry of the same suggestion is recorded for usage but does not use
    # another unit of the hourly suggestion budget.
    counts_against_limit = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)


class RepositoryFileComment(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='file_comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    branch = models.CharField(max_length=100)
    file_path = models.CharField(max_length=240)
    body = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
