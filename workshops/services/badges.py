"""
workshops/services/badges.py
==============================
Logique de débloquage des badges ateliers.

Critères :
  first-workshop   : 1er certificat obtenu
  workshop-marathon: 5 certificats obtenus
  early-bird       : réservé dans les 24h après la publication du workshop
  top-reviewer     : 3 avis (ratings) attribués
  mode-explorer    : participé aux 3 modes (onsite + online + recorded)

Déclenchement : appelé depuis workshops/signals.py via post_save
sur Certificate et Booking.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

# Définition canonique des badges (slug → données)
BADGE_DEFINITIONS = [
    {
        'slug': 'first-workshop',
        'name': 'Premier Atelier',
        'icon': 'bi-mortarboard-fill',
        'description': 'Vous avez complété votre premier atelier HackFlow.',
        'criteria': '1 certificat obtenu',
    },
    {
        'slug': 'workshop-marathon',
        'name': 'Workshop Marathon',
        'icon': 'bi-lightning-charge-fill',
        'description': 'Vous avez suivi 5 ateliers HackFlow.',
        'criteria': '5 certificats obtenus',
    },
    {
        'slug': 'early-bird',
        'name': 'Early Bird',
        'icon': 'bi-alarm-fill',
        'description': 'Réservé dans les 24h après la publication.',
        'criteria': 'Réservation < 24h après création du workshop',
    },
    {
        'slug': 'top-reviewer',
        'name': 'Top Reviewer',
        'icon': 'bi-star-fill',
        'description': 'Vous avez attribué 3 notes à des ateliers.',
        'criteria': '3 ratings remplis',
    },
    {
        'slug': 'mode-explorer',
        'name': 'Mode Explorer',
        'icon': 'bi-compass-fill',
        'description': 'Participé aux 3 formats : présentiel, live et replay.',
        'criteria': 'Un certificat de chaque mode',
    },
]


def ensure_badges_exist():
    """Crée les badges manquants en base (idempotent, 1 requête si tout existe)."""
    from workshops.models import Badge
    existing = set(Badge.objects.values_list('slug', flat=True))
    for defn in BADGE_DEFINITIONS:
        if defn['slug'] in existing:
            continue
        Badge.objects.get_or_create(
            slug=defn['slug'],
            defaults={
                'name':        defn['name'],
                'icon':        defn['icon'],
                'description': defn['description'],
                'criteria':    defn['criteria'],
            }
        )


def _has_award(user, slug: str) -> bool:
    """Vrai si le badge est déjà possédé (évite les requêtes de calcul)."""
    from workshops.models import BadgeAward
    return BadgeAward.objects.filter(user=user, badge__slug=slug).exists()


def _award(user, slug: str, reason: str, workshop=None):
    """Décerne un badge à un utilisateur (idempotent)."""
    from workshops.models import Badge, BadgeAward
    if _has_award(user, slug):
        return
    try:
        badge = Badge.objects.get(slug=slug)
        _, created = BadgeAward.objects.get_or_create(
            user=user,
            badge=badge,
            defaults={'reason': reason, 'workshop': workshop},
        )
        if created:
            # Notification
            try:
                from student.models import Notification
                from django.urls import reverse
                Notification.objects.create(
                    user=user,
                    title=f'Badge débloqué : {badge.name}',
                    message=badge.description,
                    icon=badge.icon or 'bi-award-fill',
                    url=reverse('workshops:my_bookings'),
                )
            except Exception:
                pass
            logger.info('Badge %s décerné à %s', slug, user)
    except Exception as exc:
        logger.warning('Erreur _award(%s, %s) : %s', slug, user, exc)


def check_badges_for_certificate(cert):
    """
    Vérifie et décerne les badges liés à la certification.
    Appelé après la création d'un Certificate.
    """
    from workshops.models import Certificate

    user = cert.user

    # Badge : premier atelier
    if not _has_award(user, 'first-workshop'):
        _award(user, 'first-workshop',
               'Premier atelier complété !', workshop=cert.workshop)

    # Badge : marathon (5 ateliers) — le comptage n'est fait qu'une fois.
    if not _has_award(user, 'workshop-marathon'):
        cert_count = Certificate.objects.filter(
            user=user, is_revoked=False
        ).count()
        if cert_count >= 5:
            _award(user, 'workshop-marathon',
                   f'{cert_count} ateliers complétés !', workshop=cert.workshop)

    # Badge : mode explorer (3 modes différents)
    if not _has_award(user, 'mode-explorer'):
        modes_attended = set(
            Certificate.objects.filter(user=user, is_revoked=False)
            .values_list('workshop__mode', flat=True)
        )
        if {'onsite', 'online', 'recorded'}.issubset(modes_attended):
            _award(user, 'mode-explorer',
                   'Participé aux 3 formats d\'atelier.', workshop=cert.workshop)


def check_badges_for_booking(booking):
    """
    Vérifie et décerne les badges liés à une réservation ou note.
    Appelé après la sauvegarde d'un Booking.
    """
    from workshops.models import Booking

    # Une réservation annulée ne doit pas rapporter de badge.
    if booking.status == Booking.Status.CANCELLED:
        return

    user = booking.user

    # Badge : early-bird (réservé dans les 24h après création du workshop)
    ws = booking.workshop
    if not _has_award(user, 'early-bird') and ws.created_at and booking.booked_at:
        delta = booking.booked_at - ws.created_at
        if timezone.timedelta(0) <= delta <= timezone.timedelta(hours=24):
            _award(user, 'early-bird',
                   f'Réservé tôt pour «{ws.title}»', workshop=ws)

    # Badge : top-reviewer (3 ratings)
    if not _has_award(user, 'top-reviewer'):
        rating_count = Booking.objects.filter(
            user=user, rating__isnull=False
        ).count()
        if rating_count >= 3:
            _award(user, 'top-reviewer',
                   '3 ateliers notés.', workshop=ws)
