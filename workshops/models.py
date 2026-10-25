"""
workshops/models.py
===================
4 entités principales :
  Workshop    — atelier (présentiel / live / vidéo)
  Booking     — réservation étudiant (confirmed / waiting / cancelled / attended)
  Certificate — certificat PDF vérifiable avec code unique HF-YYYY-XXXX
  Badge       — récompense débloquée automatiquement via signaux
  BadgeAward  — table de jonction M2M User↔Badge avec contexte
"""

import secrets
import string
import uuid
from datetime import timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from accounts.storage import PrivateCVStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_cert_code():
    """Génère un code de certificat au format HF-YYYY-XXXX-XXXX (alphanumérique)."""
    year = timezone.now().year
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    return f'HF-{year}-{part1}-{part2}'


def _unique_checkin_token():
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Workshop
# ---------------------------------------------------------------------------

class Workshop(models.Model):
    """Atelier : présentiel, live ou enregistré."""

    class Mode(models.TextChoices):
        ONSITE   = 'onsite',   'Présentiel'
        ONLINE   = 'online',   'Live / Visio'
        RECORDED = 'recorded', 'Vidéo enregistrée'

    class Level(models.TextChoices):
        BEGINNER     = 'beginner',     'Débutant'
        INTERMEDIATE = 'intermediate', 'Intermédiaire'
        ADVANCED     = 'advanced',     'Avancé'

    # Identité
    title          = models.CharField(max_length=160, verbose_name='Titre')
    slug           = models.SlugField(max_length=180, unique=True, blank=True)
    description    = models.TextField(verbose_name='Description')
    speaker_name   = models.CharField(max_length=120, verbose_name='Intervenant')
    speaker_company = models.CharField(max_length=120, blank=True, verbose_name='Entreprise')

    # Contenu & classification
    topic_tags     = models.JSONField(default=list, blank=True,
                                      verbose_name='Tags thématiques',
                                      help_text='Liste JSON ex. ["AWS","Docker"]')
    level          = models.CharField(max_length=16, choices=Level.choices,
                                      default=Level.BEGINNER, verbose_name='Niveau')
    mode           = models.CharField(max_length=12, choices=Mode.choices,
                                      default=Mode.ONSITE, verbose_name='Mode de diffusion')

    # Liens selon le mode
    room           = models.CharField(max_length=80, blank=True, verbose_name='Salle')
    meeting_url    = models.URLField(blank=True, verbose_name='Lien Zoom / Meet')
    replay_url     = models.URLField(blank=True, verbose_name='URL du replay')
    replay_duration = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Durée replay (min)')
    available_until = models.DateTimeField(
        null=True, blank=True, verbose_name='Accès replay jusqu\'au')
    video_file = models.FileField(
        upload_to='workshop_videos/', blank=True, null=True,
        verbose_name='Fichier vidéo (upload)')

    # Créneau
    starts_at      = models.DateTimeField(verbose_name='Début')
    ends_at        = models.DateTimeField(verbose_name='Fin')

    # Capacité
    capacity       = models.PositiveSmallIntegerField(
        default=30,
        help_text='0 = illimité (replay)',
        verbose_name='Capacité')
    is_open        = models.BooleanField(default=True, verbose_name='Inscriptions ouvertes')

    # Méta
    created_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='organized_workshops',
        verbose_name='Organisateur')
    created_at     = models.DateTimeField(auto_now_add=True)
    cover_image    = models.ImageField(
        upload_to='workshop_covers/', blank=True, null=True,
        verbose_name='Image de couverture')

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'Atelier'
        verbose_name_plural = 'Ateliers'

    # ------------------------------------------------------------------
    # Slug auto
    # ------------------------------------------------------------------
    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)
            slug = base
            n = 1
            while Workshop.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Propriétés calculées
    # ------------------------------------------------------------------
    def _prefetched_bookings(self):
        """Retourne les réservations préchargées, ou None si absentes.

        Évite les N+1 requêtes sur le catalogue : les vues qui affichent
        plusieurs ateliers utilisent ``prefetch_related('bookings')``.
        """
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        return cache.get('bookings')

    @property
    def confirmed_count(self):
        # Annotation disponible (dashboard) → aucune requête supplémentaire.
        if hasattr(self, 'nb_confirmed'):
            return self.nb_confirmed
        prefetched = self._prefetched_bookings()
        if prefetched is not None:
            return sum(1 for b in prefetched if b.status in ('confirmed', 'attended'))
        return self.bookings.filter(status__in=['confirmed', 'attended']).count()

    @property
    def seats_left(self):
        if self.capacity == 0:
            return None  # illimité
        return max(0, self.capacity - self.confirmed_count)

    @property
    def waitlist_count(self):
        if hasattr(self, 'nb_waiting'):
            return self.nb_waiting
        prefetched = self._prefetched_bookings()
        if prefetched is not None:
            return sum(1 for b in prefetched if b.status == 'waiting')
        return self.bookings.filter(status='waiting').count()

    @property
    def attendee_count(self):
        if hasattr(self, 'nb_attended'):
            return self.nb_attended
        prefetched = self._prefetched_bookings()
        if prefetched is not None:
            return sum(1 for b in prefetched if b.status == 'attended')
        return self.bookings.filter(status='attended').count()

    @property
    def average_rating(self):
        if hasattr(self, 'avg_rating'):
            return round(self.avg_rating, 1) if self.avg_rating is not None else None
        prefetched = self._prefetched_bookings()
        if prefetched is not None:
            ratings = [b.rating for b in prefetched if b.rating is not None]
        else:
            ratings = list(
                self.bookings.filter(rating__isnull=False)
                .values_list('rating', flat=True)
            )
        if not ratings:
            return None
        return round(sum(ratings) / len(ratings), 1)

    @property
    def rating_stars(self):
        """Note arrondie pour l'affichage (évite 3.7 → 3 étoiles)."""
        rating = self.average_rating
        return int(rating + 0.5) if rating is not None else 0

    @property
    def fill_rate(self):
        """Taux de remplissage 0-100 ou None si illimité."""
        if self.capacity == 0:
            return None
        return round(self.confirmed_count / self.capacity * 100)

    @property
    def is_past(self):
        return self.ends_at < timezone.now()

    @property
    def has_started(self):
        """True dès l'heure de début (comparaison date + heure système)."""
        return self.starts_at <= timezone.now()

    @property
    def is_ongoing(self):
        now = timezone.now()
        return self.starts_at <= now < self.ends_at

    @property
    def booking_closed_reason(self):
        """
        Raison pour laquelle la réservation est impossible.

        Retourne '' si l'atelier est réservable. Comparaison faite sur les
        datetime complets (donc le jour même, à l'heure près).
        """
        now = timezone.now()

        if self.mode == self.Mode.RECORDED:
            if not self.is_open:
                return 'Inscriptions fermées'
            if self.available_until and self.available_until < now:
                return 'Replay expiré'
            return ''

        if self.is_past:
            return 'Atelier terminé'
        if not self.is_open:
            return 'Inscriptions fermées'
        if self.has_started:
            return 'Atelier commencé'
        return ''

    @property
    def is_replay_available(self):
        if self.mode != Workshop.Mode.RECORDED:
            return False
        if self.available_until and self.available_until < timezone.now():
            return False
        return bool(self.replay_url)

    @property
    def google_calendar_url(self):
        """Lien pré-rempli « Ajouter à Google Calendar ».

        Aucune clé API n'est nécessaire : Google Calendar ouvre simplement
        un formulaire d'événement avec les champs déjà remplis. L'utilisateur
        garde le contrôle et clique sur « Enregistrer ».
        """
        start = self.starts_at.astimezone(
            dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        end = self.ends_at.astimezone(
            dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')

        if self.mode == self.Mode.ONSITE:
            location = self.room or 'Présentiel'
        elif self.mode == self.Mode.ONLINE:
            # Ne jamais exposer meeting_url ici : le lien Zoom reste réservé
            # aux participants inscrits (contrôle côté vue de détail).
            location = 'En ligne'
        else:
            location = 'Replay en ligne'

        site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
        details = self.description.strip()
        if site_url:
            details = f'{details}\n\nPlus d\'infos : {site_url}{self.get_absolute_url()}'

        params = {
            'action': 'TEMPLATE',
            'text': self.title,
            'dates': f'{start}/{end}',
            'details': details[:900],
            'location': location,
            'trp': 'false',
        }
        return (
            'https://calendar.google.com/calendar/render?'
            + urlencode(params)
        )

    def get_absolute_url(self):
        return reverse('workshops:detail', kwargs={'slug': self.slug})

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

class Booking(models.Model):
    """Réservation d'un étudiant à un atelier."""

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Confirmé'
        WAITING   = 'waiting',   'Liste d\'attente'
        CANCELLED = 'cancelled', 'Annulé'
        ATTENDED  = 'attended',  'Participé'

    workshop       = models.ForeignKey(
        Workshop, on_delete=models.CASCADE,
        related_name='bookings', verbose_name='Atelier')
    user           = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workshop_bookings',
        verbose_name='Étudiant')
    status         = models.CharField(
        max_length=12, choices=Status.choices,
        default=Status.CONFIRMED, verbose_name='Statut')
    seat_number    = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Numéro de place')
    checkin_token  = models.CharField(
        max_length=64, unique=True, blank=True,
        verbose_name='Token QR check-in')

    # Horodatages
    booked_at      = models.DateTimeField(auto_now_add=True)
    cancelled_at   = models.DateTimeField(null=True, blank=True)
    attended_at    = models.DateTimeField(null=True, blank=True)

    # Replay
    replay_progress = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        verbose_name='Progression replay (%)')

    # Note / avis
    rating         = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='Note (1-5)')
    comment        = models.TextField(blank=True, verbose_name='Commentaire')

    class Meta:
        verbose_name = 'Réservation'
        verbose_name_plural = 'Réservations'
        constraints = [
            models.UniqueConstraint(
                fields=['workshop', 'user'],
                name='unique_booking'),
            # Une place physique ne peut être occupée que par une seule
            # réservation active. Les annulations libèrent la place.
            models.UniqueConstraint(
                fields=['workshop', 'seat_number'],
                condition=models.Q(status__in=['confirmed', 'attended']),
                name='unique_active_seat'),
        ]
        ordering = ['booked_at']

    def save(self, *args, **kwargs):
        if not self.checkin_token:
            self.checkin_token = _unique_checkin_token()
        super().save(*args, **kwargs)

    def get_qr_url(self):
        return reverse('workshops:checkin',
                       kwargs={'pk': self.workshop_id, 'token': self.checkin_token})

    @property
    def waitlist_position(self):
        if self.status != Booking.Status.WAITING:
            return None
        cache = getattr(self.workshop, '_prefetched_objects_cache', None) or {}
        prefetched = cache.get('bookings')
        if prefetched is not None:
            earlier = sum(
                1 for b in prefetched
                if b.status == Booking.Status.WAITING
                and b.booked_at < self.booked_at
            )
            return earlier + 1
        return (
            Booking.objects.filter(
                workshop=self.workshop,
                status='waiting',
                booked_at__lt=self.booked_at,
            ).count() + 1
        )

    def __str__(self):
        return f'{self.user} → {self.workshop} [{self.status}]'


# ---------------------------------------------------------------------------
# WorkshopFavorite
# ---------------------------------------------------------------------------

class WorkshopFavorite(models.Model):
    """Atelier mis en favori par un étudiant."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workshop_favorites',
        verbose_name='Étudiant')
    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='Atelier')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Favori atelier'
        verbose_name_plural = 'Favoris ateliers'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'workshop'],
                name='unique_workshop_favorite')
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} ♥ {self.workshop}'


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------

class Certificate(models.Model):
    """Certificat de participation délivré après check-in ou replay 100%."""

    workshop   = models.ForeignKey(
        Workshop, on_delete=models.CASCADE,
        related_name='certificates', verbose_name='Atelier')
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='certificates',
        verbose_name='Bénéficiaire')
    code       = models.CharField(
        max_length=32, unique=True, default=_unique_cert_code,
        verbose_name='Code de vérification')
    serial     = models.PositiveIntegerField(
        null=True, blank=True, unique=True, verbose_name='Numéro de série')
    hours      = models.DecimalField(
        max_digits=5, decimal_places=1,
        default=1.0, verbose_name='Heures de formation')
    pdf        = models.FileField(
        upload_to='certificates/',
        storage=PrivateCVStorage(),
        blank=True, null=True,
        verbose_name='Fichier PDF')
    issued_at  = models.DateTimeField(auto_now_add=True)
    is_revoked = models.BooleanField(default=False, verbose_name='Révoqué')

    class Meta:
        verbose_name = 'Certificat'
        verbose_name_plural = 'Certificats'
        constraints = [
            models.UniqueConstraint(
                fields=['workshop', 'user'],
                name='unique_certificate')
        ]
        ordering = ['-issued_at']

    def save(self, *args, **kwargs):
        # Auto-incrément atomique du numéro de série.
        # ``serial`` est unique : en cas de course entre deux créations,
        # l'une des deux transactions échoue puis retente avec le numéro
        # suivant. Le savepoint interne permet de continuer la transaction.
        if self.serial:
            return super().save(*args, **kwargs)

        for _attempt in range(10):
            last = Certificate.objects.order_by('-serial').first()
            self.serial = (last.serial + 1) if (last and last.serial) else 1
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                if 'serial' not in str(exc).lower():
                    raise
                self.serial = None
                continue
        raise IntegrityError(
            'Impossible d\'attribuer un numéro de série unique au certificat.'
        )

    @property
    def hours_display(self):
        h = int(self.hours)
        m = int((self.hours - h) * 60)
        return f'{h}h{m:02d}' if m else f'{h}h'

    def get_verify_url(self):
        return reverse('workshops:verify', kwargs={'code': self.code})

    def __str__(self):
        return f'[{self.code}] {self.user} — {self.workshop}'


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------

class Badge(models.Model):
    """Badge débloquable par un étudiant selon des critères."""

    slug        = models.SlugField(max_length=80, unique=True)
    name        = models.CharField(max_length=120)
    icon        = models.CharField(
        max_length=80, default='bi-award-fill',
        help_text='Classe Bootstrap Icon ex. bi-star-fill')
    description = models.TextField(blank=True)
    criteria    = models.TextField(
        blank=True,
        help_text='Description textuelle du critère de débloquage')
    awarded_to  = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='BadgeAward',
        related_name='workshop_badges',
        blank=True)

    class Meta:
        verbose_name = 'Badge'
        verbose_name_plural = 'Badges'

    def __str__(self):
        return self.name


class BadgeAward(models.Model):
    """Table de jonction Badge ↔ User avec contexte."""

    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='badge_awards')
    badge      = models.ForeignKey(
        Badge, on_delete=models.CASCADE,
        related_name='awards')
    awarded_at = models.DateTimeField(auto_now_add=True)
    reason     = models.CharField(max_length=240, blank=True)
    workshop   = models.ForeignKey(
        Workshop, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='badge_awards')

    class Meta:
        verbose_name = 'Attribution de badge'
        verbose_name_plural = 'Attributions de badges'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'badge'],
                name='unique_badge_award')
        ]
        ordering = ['-awarded_at']

    def __str__(self):
        return f'{self.user} — {self.badge}'


# ---------------------------------------------------------------------------
# WorkshopActivity  (journal d'activité bonus)
# ---------------------------------------------------------------------------

class WorkshopActivity(models.Model):
    """Journal d'audit des actions importantes sur les ateliers."""

    class Kind(models.TextChoices):
        CREATED   = 'created',   'Créé'
        UPDATED   = 'updated',   'Modifié'
        CLOSED    = 'closed',    'Fermé'
        BOOKED    = 'booked',    'Réservé'
        CANCELLED = 'cancelled', 'Annulé'
        CHECKIN   = 'checkin',   'Check-in'
        CERT      = 'cert',      'Certificat émis'
        REVOKED   = 'revoked',   'Certificat révoqué'
        BADGE     = 'badge',     'Badge décerné'

    workshop   = models.ForeignKey(
        Workshop, on_delete=models.CASCADE,
        related_name='activities')
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='workshop_activities')
    kind       = models.CharField(max_length=12, choices=Kind.choices)
    detail     = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Activité atelier'
        verbose_name_plural = 'Activités ateliers'

    def __str__(self):
        return f'[{self.kind}] {self.workshop} — {self.user}'


# ---------------------------------------------------------------------------
# WorkshopQuiz  (quiz de compréhension pour les ateliers en replay)
# ---------------------------------------------------------------------------

class WorkshopQuiz(models.Model):
    """Question de quiz liée à un atelier en mode replay."""

    workshop = models.ForeignKey(
        Workshop, on_delete=models.CASCADE,
        related_name='quiz_questions', verbose_name='Atelier')
    question = models.TextField(verbose_name='Question')
    option_a = models.CharField(max_length=200, verbose_name='Option A')
    option_b = models.CharField(max_length=200, verbose_name='Option B')
    option_c = models.CharField(max_length=200, verbose_name='Option C')
    option_d = models.CharField(max_length=200, verbose_name='Option D')
    correct_index = models.PositiveSmallIntegerField(
        default=0,
        help_text='Index de la bonne réponse (0=A, 1=B, 2=C, 3=D)',
        verbose_name='Index bonne réponse')
    explanation = models.TextField(
        blank=True, verbose_name='Explication de la bonne réponse')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='created_quiz_questions',
        verbose_name='Créé par')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Question de quiz'
        verbose_name_plural = 'Questions de quiz'
        ordering = ['created_at']

    def __str__(self):
        return f'Q: {self.question[:50]}...'

    def options(self):
        return [self.option_a, self.option_b, self.option_c, self.option_d]

    def correct_option(self):
        return self.options()[self.correct_index]
