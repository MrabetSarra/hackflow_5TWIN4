from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from student.models import MentorRequest, Submission, Team

# Grille de jugement par défaut : créée automatiquement par la migration 0002
# et reprise ici pour pouvoir la restaurer ou la tester.
DEFAULT_CRITERIA = [
    {
        'code': 'innovation',
        'name': 'Innovation et originalité',
        'description': "Caractère novateur de l'idée et originalité de la solution proposée.",
        'weight': 25,
        'order': 1,
    },
    {
        'code': 'technique',
        'name': 'Qualité technique',
        'description': "Architecture, qualité du code, robustesse et maîtrise des technologies.",
        'weight': 25,
        'order': 2,
    },
    {
        'code': 'design_ux',
        'name': 'Design et expérience utilisateur',
        'description': "Ergonomie, clarté de l'interface et qualité du parcours utilisateur.",
        'weight': 25,
        'order': 3,
    },
    {
        'code': 'valeur_presentation',
        'name': 'Valeur, usages et présentation',
        'description': "Utilité réelle, cas d'usage, modèle de valeur et qualité du pitch.",
        'weight': 25,
        'order': 4,
    },
]


class Criterion(models.Model):
    """Critère pondéré de la grille de jugement, partagé par le jury et les mentors."""

    class Scope(models.TextChoices):
        BOTH = 'both', 'Jury et mentors'
        JURY = 'jury', 'Jury uniquement'
        MENTOR = 'mentor', 'Mentors uniquement'

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    weight = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Pondération en pourcentage.',
    )
    max_score = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.BOTH)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'critère de jugement'
        verbose_name_plural = 'grille de jugement'

    def __str__(self):
        return f'{self.name} ({self.weight}%)'

    @classmethod
    def for_scope(cls, scope):
        """Critères actifs utilisables par le jury ou par les mentors."""
        return cls.objects.filter(is_active=True, scope__in=(scope, cls.Scope.BOTH))

    @classmethod
    def total_weight(cls, scope):
        return cls.for_scope(scope).aggregate(total=Sum('weight'))['total'] or 0

    @classmethod
    def ensure_default_grid(cls):
        """Crée les critères par défaut manquants sans écraser les modifications de l'admin."""
        for data in DEFAULT_CRITERIA:
            cls.objects.get_or_create(code=data['code'], defaults=data)


def _validate_mentor(user, field):
    if user is not None and getattr(user, 'role', None) != 'mentor':
        raise ValidationError({field: "Cet utilisateur n'a pas le rôle mentor."})


class MentorAssignment(models.Model):
    """Équipe suivie par un mentor.

    Le mentor choisit lui-même ses équipes (« Suivre cette équipe ») ; le suivi est aussi
    créé automatiquement quand il prend en charge un ticket ou planifie une session.
    Le module organisateur peut réutiliser ce modèle, mais le module mentor n'en dépend pas.
    """

    class Source(models.TextChoices):
        MENTOR = 'mentor', 'Choisie par le mentor'
        AUTO = 'auto', 'Automatique (ticket ou session)'
        ORGANIZER = 'organizer', "Affectée par l'organisation"

    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentor_assignments',
        limit_choices_to={'role': 'mentor'},
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='mentor_assignments')
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MENTOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['team__name']
        verbose_name = 'équipe suivie'
        verbose_name_plural = 'équipes suivies'
        constraints = [
            models.UniqueConstraint(fields=['mentor', 'team'], name='unique_mentor_team_assignment'),
        ]

    def __str__(self):
        return f'{self.mentor} → {self.team}'

    def clean(self):
        _validate_mentor(self.mentor if self.mentor_id else None, 'mentor')

    @classmethod
    def follow(cls, mentor, team, source=Source.MENTOR):
        """Fait suivre l'équipe par le mentor ; sans effet si c'est déjà le cas."""
        _validate_mentor(mentor, 'mentor')
        assignment, _created = cls.objects.get_or_create(mentor=mentor, team=team, defaults={'source': source})
        return assignment

    @classmethod
    def is_following(cls, mentor, team):
        return cls.objects.filter(mentor=mentor, team=team).exists()


class MentoringSession(models.Model):
    """Session d'accompagnement planifiée entre un mentor et une équipe."""

    class Status(models.TextChoices):
        PLANNED = 'planned', 'Planifiée'
        CONFIRMED = 'confirmed', 'Confirmée'
        DONE = 'done', 'Terminée'
        CANCELLED = 'cancelled', 'Annulée'

    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentoring_sessions',
        limit_choices_to={'role': 'mentor'},
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='mentoring_sessions')
    help_request = models.ForeignKey(
        MentorRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='mentoring_sessions',
    )
    topic = models.CharField(max_length=180)
    notes = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    meeting_url = models.URLField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'session de mentorat'
        verbose_name_plural = 'sessions de mentorat'
        indexes = [models.Index(fields=['mentor', 'starts_at'])]

    def __str__(self):
        return f'{self.team} — {self.topic}'

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors['ends_at'] = 'La fin doit être après le début.'
        if self.help_request_id and self.team_id and self.help_request.team_id not in (None, self.team_id):
            errors['help_request'] = "Cette demande d'aide appartient à une autre équipe."
        if errors:
            raise ValidationError(errors)
        _validate_mentor(self.mentor if self.mentor_id else None, 'mentor')

    @property
    def is_upcoming(self):
        return self.status in (self.Status.PLANNED, self.Status.CONFIRMED) and self.ends_at >= timezone.now()


class MentorEvaluation(models.Model):
    """Évaluation multi-critères d'une soumission de projet par un mentor (avis consultatif)."""

    class PitchReadiness(models.TextChoices):
        NOT_READY = 'not_ready', 'Pas prêt'
        ON_TRACK = 'on_track', 'En bonne voie'
        READY = 'ready', 'Prêt'

    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentor_evaluations',
        limit_choices_to={'role': 'mentor'},
    )
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='mentor_evaluations')
    general_comment = models.TextField(blank=True)
    pitch_readiness = models.CharField(
        max_length=12, choices=PitchReadiness.choices, default=PitchReadiness.ON_TRACK,
    )
    is_shared = models.BooleanField(default=False)
    shared_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'évaluation mentor'
        verbose_name_plural = 'évaluations mentor'
        constraints = [
            models.UniqueConstraint(fields=['mentor', 'submission'], name='unique_mentor_submission_evaluation'),
        ]

    def __str__(self):
        return f'{self.submission.team} — {self.mentor}'

    def clean(self):
        _validate_mentor(self.mentor if self.mentor_id else None, 'mentor')

    @property
    def team(self):
        return self.submission.team

    def weighted_total(self, scale=20):
        """Note pondérée ramenée sur `scale` (20 par défaut), ou None si aucune note."""
        scores = list(self.scores.select_related('criterion'))
        total_weight = sum(s.criterion.weight for s in scores)
        if not total_weight:
            return None
        weighted = sum(Decimal(s.score) / s.criterion.max_score * s.criterion.weight for s in scores)
        return round(weighted / total_weight * scale, 2)

    def share(self):
        self.is_shared = True
        self.shared_at = timezone.now()
        self.save(update_fields=['is_shared', 'shared_at', 'updated_at'])


class EvaluationScore(models.Model):
    """Note attribuée sur un critère de la grille."""

    evaluation = models.ForeignKey(MentorEvaluation, on_delete=models.CASCADE, related_name='scores')
    criterion = models.ForeignKey(Criterion, on_delete=models.PROTECT, related_name='mentor_scores')
    score = models.DecimalField(max_digits=4, decimal_places=1, validators=[MinValueValidator(0)])
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['criterion__order']
        constraints = [
            models.UniqueConstraint(fields=['evaluation', 'criterion'], name='unique_evaluation_criterion_score'),
        ]

    def __str__(self):
        return f'{self.criterion.name} : {self.score}/{self.criterion.max_score}'

    def clean(self):
        if self.criterion_id and self.score is not None and self.score > self.criterion.max_score:
            raise ValidationError({'score': f'La note maximale est {self.criterion.max_score}.'})


class RequestTriage(models.Model):
    """Analyse IA (Ollama local) d'une demande d'aide : catégorie, urgence, résumé, mentor suggéré."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        RUNNING = 'running', 'Analyse en cours'
        DONE = 'done', 'Terminée'
        FAILED = 'failed', 'Indisponible'

    help_request = models.OneToOneField(MentorRequest, on_delete=models.CASCADE, related_name='triage')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    suggested_category = models.CharField(max_length=120, blank=True)
    suggested_urgency = models.CharField(max_length=12, choices=MentorRequest.Urgency.choices, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    suggested_mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    # Valeurs corrigées par un mentor : servent d'étiquettes de référence pour les métriques.
    corrected_category = models.CharField(max_length=120, blank=True)
    corrected_urgency = models.CharField(max_length=12, choices=MentorRequest.Urgency.choices, blank=True)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    model_name = models.CharField(max_length=80, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'tri IA de demande'
        verbose_name_plural = 'tris IA de demandes'
        indexes = [models.Index(fields=['status'])]

    def __str__(self):
        return f'Tri IA #{self.help_request_id} ({self.get_status_display()})'

    @property
    def final_category(self):
        return self.corrected_category or self.suggested_category

    @property
    def final_urgency(self):
        return self.corrected_urgency or self.suggested_urgency
