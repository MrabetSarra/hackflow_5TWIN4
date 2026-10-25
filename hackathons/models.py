from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif']
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
RESOURCE_EXTENSIONS = ['pdf', 'zip', 'md', 'txt', 'csv', 'json', 'docx', 'pptx', 'xlsx', 'png', 'jpg', 'jpeg']


def validate_upload_size(upload):
    if getattr(upload, 'size', 0) > MAX_UPLOAD_BYTES:
        raise ValidationError('Le fichier ne doit pas dépasser 5 Mo.')


def _unique_slug(model, value, instance_pk=None, fallback='item'):
    base = slugify(value)[:200] or fallback
    slug, n = base, 2
    while model.objects.filter(slug=slug).exclude(pk=instance_pk).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


class Track(models.Model):
    name = models.CharField('Nom', max_length=120, unique=True)
    slug = models.SlugField('Identifiant (slug)', max_length=140, unique=True, blank=True)
    description = models.TextField('Description', blank=True)
    image = models.ImageField(
        'Image / icône', upload_to='hackathons/tracks/', blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_upload_size],
    )
    domain = models.CharField('Domaine', max_length=80, blank=True)
    keywords = models.CharField('Mots-clés (séparés par des virgules)', max_length=250, blank=True)
    is_active = models.BooleanField('Actif', default=True)
    created_at = models.DateTimeField('Créé le', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'track'
        verbose_name_plural = 'tracks'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Track, self.name, self.pk, 'track')
        super().save(*args, **kwargs)

    @property
    def keyword_list(self):
        return [k.strip() for k in self.keywords.split(',') if k.strip()]

    @property
    def published_hackathon_count(self):
        return self.hackathons.filter(status=HackathonProfile.Status.PUBLISHED).count()


class HackathonProfile(models.Model):
    """Détails d'un hackathon, rattaché à l'événement existant student.Hackathon sans le modifier."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Brouillon'
        PUBLISHED = 'published', 'Publié'
        CANCELLED = 'cancelled', 'Annulé'
        ARCHIVED = 'archived', 'Archivé'

    class Stage(models.TextChoices):
        REGISTRATION_OPEN = 'registration_open', 'Inscriptions ouvertes'
        REGISTRATION_CLOSED = 'registration_closed', 'Inscriptions closes'
        ONGOING = 'ongoing', 'En cours'
        EVALUATION = 'evaluation', 'Évaluation'
        FINISHED = 'finished', 'Terminé'

    event = models.OneToOneField('student.Hackathon', on_delete=models.CASCADE, related_name='profile', verbose_name='Événement')
    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name='hackathons', verbose_name='Track')
    slug = models.SlugField('Identifiant (slug)', max_length=200, unique=True, blank=True)
    short_description = models.CharField('Description courte', max_length=240, blank=True)
    description = models.TextField('Description complète', blank=True)
    banner = models.ImageField(
        'Bannière', upload_to='hackathons/banners/', blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_upload_size],
    )
    registration_deadline = models.DateTimeField("Date limite d'inscription", null=True, blank=True)
    max_participants = models.PositiveIntegerField(
        'Capacité maximale', null=True, blank=True, validators=[MinValueValidator(1)],
    )
    rules = models.TextField('Règlement', blank=True)
    status = models.CharField('Statut de publication', max_length=12, choices=Status.choices, default=Status.DRAFT)
    stage = models.CharField('Étape du hackathon', max_length=20, choices=Stage.choices, default=Stage.REGISTRATION_OPEN)
    latitude = models.FloatField('Latitude', null=True, blank=True)
    longitude = models.FloatField('Longitude', null=True, blank=True)
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='organized_hackathons',
        verbose_name='Organisateur',
    )
    created_at = models.DateTimeField('Créé le', auto_now_add=True)

    class Meta:
        ordering = ['event__starts_at']
        verbose_name = 'hackathon'
        verbose_name_plural = 'hackathons'

    def __str__(self):
        return self.event.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(HackathonProfile, self.event.name, self.pk, 'hackathon')
        super().save(*args, **kwargs)

    @property
    def title(self):
        return self.event.name

    @property
    def starts_at(self):
        return self.event.starts_at

    @property
    def ends_at(self):
        return self.event.ends_at

    @property
    def location(self):
        return self.event.location

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    @property
    def phase(self):
        """Phase calculée à partir des dates (évite un statut redondant en base)."""
        now = timezone.now()
        if self.status == self.Status.CANCELLED:
            return 'cancelled'
        if now < self.event.starts_at:
            return 'upcoming'
        if now <= self.event.ends_at:
            return 'ongoing'
        return 'finished'

    @property
    def phase_label(self):
        return {'cancelled': 'Annulé', 'upcoming': 'À venir', 'ongoing': 'En cours', 'finished': 'Terminé'}[self.phase]

    @property
    def phase_color(self):
        return {'cancelled': 'danger', 'upcoming': 'primary', 'ongoing': 'success', 'finished': 'secondary'}[self.phase]

    @property
    def current_stage(self):
        """Étape effective : les inscriptions se ferment seules à la date limite ou au début du hackathon."""
        if self.stage == self.Stage.REGISTRATION_OPEN:
            deadline = self.registration_deadline or self.event.starts_at
            if timezone.now() > min(deadline, self.event.starts_at):
                return self.Stage.REGISTRATION_CLOSED
        return self.stage

    @property
    def current_stage_label(self):
        return self.Stage(self.current_stage).label

    @property
    def stage_color(self):
        return {
            'registration_open': 'success', 'registration_closed': 'warning', 'ongoing': 'primary',
            'evaluation': 'info', 'finished': 'secondary',
        }[self.current_stage]

    @property
    def stage_steps(self):
        """Étapes du cycle de vie avec leur état : done (vert), current (bleu), todo (gris)."""
        values = [value for value, _label in self.Stage.choices]
        current = values.index(self.current_stage)
        return [
            {'value': value, 'label': label, 'number': i + 1,
             'state': 'done' if i < current else 'current' if i == current else 'todo'}
            for i, (value, label) in enumerate(self.Stage.choices)
        ]

    @property
    def status_color(self):
        return {'draft': 'warning', 'published': 'success', 'cancelled': 'danger', 'archived': 'secondary'}[self.status]

    @property
    def registration_open(self):
        if self.status != self.Status.PUBLISHED or self.current_stage != self.Stage.REGISTRATION_OPEN:
            return False
        if self.phase in ('cancelled', 'finished'):
            return False
        deadline = self.registration_deadline or self.event.starts_at
        return timezone.now() <= deadline

    @property
    def published_challenges(self):
        return self.challenges.filter(status=Challenge.Status.PUBLISHED)

    @property
    def mode_label(self):
        return self.event.location or 'Lieu à préciser'

    def get_absolute_url(self):
        return reverse('hackathons:hackathon_detail', args=[self.slug])


class Challenge(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Brouillon'
        PUBLISHED = 'published', 'Publié'
        ARCHIVED = 'archived', 'Archivé'

    class Difficulty(models.TextChoices):
        BEGINNER = 'beginner', 'Débutant'
        INTERMEDIATE = 'intermediate', 'Intermédiaire'
        ADVANCED = 'advanced', 'Avancé'
        EXPERT = 'expert', 'Expert'

    hackathon = models.ForeignKey(HackathonProfile, on_delete=models.CASCADE, related_name='challenges')
    title = models.CharField('Titre', max_length=180)
    short_description = models.CharField('Description courte', max_length=240, blank=True)
    description = models.TextField('Description détaillée', blank=True)
    objectives = models.TextField('Objectifs', blank=True)
    problem_statement = models.TextField('Problématique', blank=True)
    constraints = models.TextField('Contraintes', blank=True)
    deliverables = models.TextField('Livrables attendus', blank=True)
    guidelines = models.TextField('Critères / consignes spécifiques', blank=True)
    difficulty = models.CharField('Difficulté', max_length=14, choices=Difficulty.choices, default=Difficulty.INTERMEDIATE)
    technologies = models.CharField('Technologies recommandées (séparées par des virgules)', max_length=250, blank=True)
    reward = models.CharField('Prix / récompense', max_length=160, blank=True)
    status = models.CharField('Statut de publication', max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField('Créé le', auto_now_add=True)

    class Meta:
        ordering = ['title']
        verbose_name = 'challenge'
        verbose_name_plural = 'challenges'

    def __str__(self):
        return self.title

    @property
    def difficulty_color(self):
        return {'beginner': 'success', 'intermediate': 'info', 'advanced': 'warning', 'expert': 'danger'}[self.difficulty]

    @property
    def status_color(self):
        return {'draft': 'warning', 'published': 'success', 'archived': 'secondary'}[self.status]

    @property
    def technology_list(self):
        return [t.strip() for t in self.technologies.split(',') if t.strip()]

    def active_registrations(self):
        return self.registrations.filter(status=Registration.Status.CONFIRMED)

    @property
    def active_announcements(self):
        now = timezone.now()
        return self.flash_announcements.filter(is_published=True, publish_at__lte=now).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))

    @property
    def published_resources(self):
        return self.resources.filter(is_published=True)

    @property
    def registered_team_names(self):
        return sorted({r.team.name for r in self.active_registrations().select_related('team') if r.team})

    @property
    def slots_used(self):
        """Une équipe compte pour une place, quel que soit le nombre de ses membres inscrits."""
        keys = {('t', r.team_id) if r.team_id else ('u', r.user_id) for r in self.active_registrations()}
        return len(keys)

    @property
    def deadline(self):
        return self.hackathon.registration_deadline or self.hackathon.starts_at

    @property
    def registration_open(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.hackathon.registration_open
            and timezone.now() <= self.deadline
        )


class Registration(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Confirmée'
        CANCELLED = 'cancelled', 'Annulée'

    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='challenge_registrations', verbose_name='Étudiant')
    team = models.ForeignKey('student.Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='challenge_registrations', verbose_name='Équipe')
    status = models.CharField('Statut', max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    registered_at = models.DateTimeField("Date d'inscription", default=timezone.now)
    cancelled_at = models.DateTimeField("Date d'annulation", null=True, blank=True)

    class Meta:
        ordering = ['-registered_at']
        verbose_name = 'inscription'
        verbose_name_plural = 'inscriptions'
        constraints = [
            models.UniqueConstraint(
                fields=['challenge', 'user'], condition=models.Q(status='confirmed'),
                name='unique_active_challenge_registration',
            ),
        ]

    def __str__(self):
        return f'{self.user} — {self.challenge}'

    @property
    def status_color(self):
        return 'success' if self.status == self.Status.CONFIRMED else 'secondary'


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hackathon_favorites')
    hackathon = models.ForeignKey(HackathonProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='favorites')
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, null=True, blank=True, related_name='favorites')
    created_at = models.DateTimeField('Ajouté le', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'favori'
        verbose_name_plural = 'favoris'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(hackathon__isnull=False, challenge__isnull=True)
                    | models.Q(hackathon__isnull=True, challenge__isnull=False)
                ),
                name='favorite_has_exactly_one_target',
            ),
            models.UniqueConstraint(
                fields=['user', 'hackathon'], condition=models.Q(challenge__isnull=True),
                name='unique_user_favorite_hackathon',
            ),
            models.UniqueConstraint(
                fields=['user', 'challenge'], condition=models.Q(hackathon__isnull=True),
                name='unique_user_favorite_challenge',
            ),
        ]

    def __str__(self):
        target = self.hackathon or self.challenge
        return f'{self.user} — {target}'


class MentorFeedback(models.Model):
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hackathon_feedback',
        limit_choices_to={'role': 'mentor'}, verbose_name='Mentor',
    )
    hackathon = models.ForeignKey(
        HackathonProfile, on_delete=models.CASCADE, null=True, blank=True,
        related_name='mentor_feedback', verbose_name='Hackathon',
    )
    challenge = models.ForeignKey(
        Challenge, on_delete=models.CASCADE, null=True, blank=True,
        related_name='mentor_feedback', verbose_name='Challenge',
    )
    rating = models.PositiveSmallIntegerField(
        'Note sur 5', null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    review = models.TextField('Avis', blank=True)
    ideas = models.TextField('Idées et suggestions', blank=True)
    created_at = models.DateTimeField('Envoyé le', auto_now_add=True)
    updated_at = models.DateTimeField('Modifié le', auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'avis mentor'
        verbose_name_plural = 'avis mentors'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(hackathon__isnull=False, challenge__isnull=True)
                    | models.Q(hackathon__isnull=True, challenge__isnull=False)
                ),
                name='mentor_feedback_has_exactly_one_target',
            ),
            models.UniqueConstraint(
                fields=['mentor', 'hackathon'], condition=models.Q(challenge__isnull=True),
                name='unique_mentor_feedback_hackathon',
            ),
            models.UniqueConstraint(
                fields=['mentor', 'challenge'], condition=models.Q(hackathon__isnull=True),
                name='unique_mentor_feedback_challenge',
            ),
        ]

    def __str__(self):
        target = self.hackathon or self.challenge
        return f'Avis de {self.mentor} — {target}'


class AIJob(models.Model):
    """Requête IA exécutée en arrière-plan (Celery) ; sert aussi de journal pour les métriques."""

    class Feature(models.TextChoices):
        HACKATHON_DRAFT = 'hackathon_draft', 'Rédaction de hackathon'
        CHALLENGE_DRAFT = 'challenge_draft', 'Rédaction de challenge'
        STUDENT_COACH = 'student_coach', 'Coach IA étudiant'
        STUDENT_RECOMMEND = 'student_recommend', 'Recommandations étudiant'
        MENTOR_EXPLAIN = 'mentor_explain', 'Explication mentor'

    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        RUNNING = 'running', 'En cours'
        DONE = 'done', 'Terminée'
        FAILED = 'failed', 'Échouée'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hackathon_ai_jobs')
    feature = models.CharField('Fonctionnalité', max_length=20, choices=Feature.choices)
    payload = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField('Statut', max_length=8, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.CharField('Erreur', max_length=400, blank=True)
    model_used = models.CharField('Modèle utilisé', max_length=80, blank=True)
    fallback_used = models.BooleanField('Modèle de secours utilisé', default=False)
    primary_error = models.CharField('Erreur du modèle principal', max_length=300, blank=True)
    cached = models.BooleanField('Réponse issue du cache', default=False)
    latency_ms = models.PositiveIntegerField('Temps de réponse (ms)', default=0)
    queue_ms = models.PositiveIntegerField('Attente en file (ms)', default=0)
    input_chars = models.PositiveIntegerField(default=0)
    output_chars = models.PositiveIntegerField(default=0)
    feedback = models.SmallIntegerField('Retour utilisateur', null=True, blank=True)
    created_at = models.DateTimeField('Créée le', auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField('Terminée le', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'requête IA'
        verbose_name_plural = 'requêtes IA'

    def __str__(self):
        return f'{self.get_feature_display()} — {self.get_status_display()}'


class ScheduleItem(models.Model):
    class Kind(models.TextChoices):
        OPENING = 'opening', 'Ouverture'
        DEV_START = 'dev_start', 'Début du développement'
        WORKSHOP = 'workshop', 'Atelier technique'
        MENTORING = 'mentoring', 'Permanence de mentorat'
        CODE_FREEZE = 'code_freeze', 'Gel du code'
        DEMO = 'demo', 'Démonstrations'
        DELIBERATION = 'deliberation', 'Délibération'
        RESULTS = 'results', 'Annonce des résultats'
        CLOSING = 'closing', 'Clôture'
        OTHER = 'other', 'Autre'

    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='schedule_items')
    title = models.CharField('Titre', max_length=180)
    kind = models.CharField('Type', max_length=14, choices=Kind.choices, default=Kind.OTHER)
    starts_at = models.DateTimeField('Début')
    ends_at = models.DateTimeField('Fin', null=True, blank=True)
    location = models.CharField('Lieu ou lien', max_length=200, blank=True)
    description = models.TextField('Description', blank=True)
    is_key_step = models.BooleanField('Étape clé', default=False)
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mentoring_slots', limit_choices_to={'role': 'mentor'}, verbose_name='Mentor responsable',
    )

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'étape du programme'
        verbose_name_plural = 'programme'

    def __str__(self):
        return self.title

    @property
    def state(self):
        now = timezone.now()
        end = self.ends_at or self.starts_at
        if now < self.starts_at:
            return 'upcoming'
        return 'ongoing' if now <= end else 'done'


class FlashAnnouncement(models.Model):
    class Level(models.TextChoices):
        INFO = 'info', 'Information'
        URGENT = 'urgent', 'Urgent'

    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='flash_announcements')
    message = models.CharField('Message', max_length=500)
    level = models.CharField('Niveau', max_length=8, choices=Level.choices, default=Level.INFO)
    publish_at = models.DateTimeField('Date de publication', default=timezone.now)
    expires_at = models.DateTimeField("Date d'expiration", null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='flash_announcements', verbose_name='Auteur')
    is_published = models.BooleanField('Publiée', default=True)

    class Meta:
        ordering = ['-publish_at']
        verbose_name = 'annonce flash'
        verbose_name_plural = 'annonces flash'

    def __str__(self):
        return self.message[:60]

    @property
    def is_active(self):
        now = timezone.now()
        return self.is_published and self.publish_at <= now and (self.expires_at is None or self.expires_at > now)


class HackathonResource(models.Model):
    class Category(models.TextChoices):
        RULES = 'rules', 'Règlement'
        STARTER = 'starter', 'Starter kit'
        TEMPLATE = 'template', 'Template'
        DOCS = 'docs', 'Documentation'
        API = 'api', 'Lien API'
        DATASET = 'dataset', 'Jeu de données'
        GUIDELINES = 'guidelines', 'Consignes'
        WIFI = 'wifi', 'Informations Wi-Fi'
        OTHER = 'other', 'Autre'

    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField('Titre', max_length=160)
    description = models.TextField('Description', blank=True)
    category = models.CharField('Catégorie', max_length=12, choices=Category.choices, default=Category.OTHER)
    url = models.URLField('Lien', blank=True)
    file = models.FileField(
        'Fichier', upload_to='hackathons/resources/', blank=True,
        validators=[FileExtensionValidator(RESOURCE_EXTENSIONS), validate_upload_size],
    )
    is_published = models.BooleanField('Publiée', default=True)

    class Meta:
        ordering = ['category', 'title']
        verbose_name = 'ressource'
        verbose_name_plural = 'ressources'

    def __str__(self):
        return self.title
