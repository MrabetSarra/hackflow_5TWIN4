"""
workshops/services/reminders.py
================================
Rappels non bloquants envoyés aux étudiants :

  * démarrage imminent (24 h avant un atelier présentiel ou live) ;
  * invitation à laisser un avis une fois l'atelier terminé.

Les horodatages ``reminder_sent_at`` / ``feedback_reminder_sent_at``
garantissent qu'un rappel n'est envoyé qu'une seule fois.
"""

from __future__ import annotations

import logging

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

REMINDER_WINDOW_HOURS = 24


def _notify(user, title, message, icon, url):
    try:
        from student.models import Notification
        Notification.objects.create(
            user=user, title=title, message=message, icon=icon, url=url)
    except Exception:
        logger.exception('Notification atelier impossible pour %s', user)


def _human_delay(minutes: int) -> str:
    if minutes < 60:
        return f'dans {max(minutes, 1)} min'
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f'dans {hours} h {remaining:02d}'
    return f'dans {hours} h'


def send_starting_soon_reminders(user=None, now=None,
                                 window_hours: int = REMINDER_WINDOW_HOURS) -> int:
    """
    Notifie les réservations confirmées dont l'atelier démarre dans moins de
    ``window_hours`` heures. Retourne le nombre de rappels créés.
    """
    from workshops.models import Booking

    now = now or timezone.now()
    limit = now + timezone.timedelta(hours=window_hours)

    queryset = Booking.objects.filter(
        status=Booking.Status.CONFIRMED,
        workshop__mode__in=['onsite', 'online'],
        workshop__starts_at__gt=now,
        workshop__starts_at__lte=limit,
        reminder_sent_at__isnull=True,
    ).select_related('user', 'workshop')

    if user is not None:
        queryset = queryset.filter(user=user)

    sent = 0
    for booking in queryset:
        workshop = booking.workshop
        minutes = int((workshop.starts_at - now).total_seconds() // 60)
        delay = _human_delay(minutes)
        details = []
        if workshop.mode == workshop.Mode.ONLINE and workshop.meeting_url:
            details.append('le lien de visio est disponible dans votre réservation')
        elif workshop.room:
            details.append(f'salle : {workshop.room}')
        suffix = f" ({', '.join(details)})" if details else ''

        _notify(
            booking.user,
            title='Votre atelier commence bientôt',
            message=(
                f'« {workshop.title} » démarre {delay}{suffix}. '
                f'Préparez-vous et consultez les détails de votre réservation.'
            ),
            icon='bi-alarm-fill',
            url=reverse('workshops:detail', kwargs={'slug': workshop.slug}),
        )
        updated = Booking.objects.filter(
            pk=booking.pk, reminder_sent_at__isnull=True,
        ).update(reminder_sent_at=now)
        sent += updated

    return sent


def send_feedback_reminders(user=None, now=None) -> int:
    """
    Invite à noter les ateliers terminés qui n'ont pas encore reçu d'avis.
    Couvre aussi les replays validés (booking ``attended``).
    """
    from workshops.models import Booking

    now = now or timezone.now()

    queryset = Booking.objects.filter(
        rating__isnull=True,
        feedback_reminder_sent_at__isnull=True,
    ).filter(
        Q(status=Booking.Status.ATTENDED)
        | Q(
            status=Booking.Status.CONFIRMED,
            workshop__mode__in=['onsite', 'online'],
            workshop__ends_at__lt=now,
        )
    ).select_related('user', 'workshop')

    if user is not None:
        queryset = queryset.filter(user=user)

    sent = 0
    for booking in queryset:
        workshop = booking.workshop
        _notify(
            booking.user,
            title='Votre avis compte',
            message=(
                f'Comment s\'est passé « {workshop.title} » ? '
                f'Donnez votre note et laissez un commentaire pour aider les prochains participants.'
            ),
            icon='bi-star-fill',
            url=reverse('workshops:rate', kwargs={'pk': workshop.pk}),
        )
        updated = Booking.objects.filter(
            pk=booking.pk, feedback_reminder_sent_at__isnull=True,
        ).update(feedback_reminder_sent_at=now)
        sent += updated

    return sent


def dispatch_reminders_for_user(user) -> dict:
    """Envoie les deux types de rappels pour un étudiant connecté."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'starting_soon': 0, 'feedback': 0}
    if getattr(user, 'role', None) != 'student':
        return {'starting_soon': 0, 'feedback': 0}

    return {
        'starting_soon': send_starting_soon_reminders(user=user),
        'feedback': send_feedback_reminders(user=user),
    }
