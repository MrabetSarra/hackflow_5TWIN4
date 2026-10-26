"""Commande : envoyer les rappels de démarrage et de feedback des ateliers."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from workshops.services.reminders import (send_feedback_reminders,
                                          send_starting_soon_reminders)


class Command(BaseCommand):
    help = 'Envoie les rappels de démarrage (24 h) et les invitations au feedback.'

    def handle(self, *args, **options):
        now = timezone.now()
        starting = send_starting_soon_reminders(now=now)
        feedback = send_feedback_reminders(now=now)
        self.stdout.write(self.style.SUCCESS(
            f'Rappels envoyés : {starting} démarrage(s), {feedback} feedback(s).'
        ))
