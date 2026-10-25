"""
Commande de démonstration du module Ateliers.

    python manage.py seed_workshops

Crée (de façon idempotente) :
  - les 5 badges du module,
  - 1 organisateur de démo si aucun admin n'existe,
  - 4 étudiants de démo si nécessaire,
  - 5 ateliers passés (pour entraîner la prédiction IA),
  - 5 ateliers à venir couvrant les 3 modes (présentiel / live / replay),
  - des réservations : confirmées, liste d'attente, présences + certificats + notes.

Comptes créés (si absents) :
  organisateur : orga.hackflow / HackFlow2026!
  étudiants    : demo.workshop1..4 / HackFlow2026!
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from workshops.models import Booking, Certificate, Workshop
from workshops.services.badges import ensure_badges_exist


class Command(BaseCommand):
    help = "Crée des ateliers, réservations et certificats de démonstration."

    def handle(self, *args, **options):
        User = get_user_model()
        now = timezone.now()

        # ------------------------------------------------------------------
        # Badges
        # ------------------------------------------------------------------
        ensure_badges_exist()

        # ------------------------------------------------------------------
        # Organisateur
        # ------------------------------------------------------------------
        organizer = User.objects.filter(role='admin').first()
        if not organizer:
            organizer, created = User.objects.get_or_create(
                username='orga.hackflow',
                defaults={
                    'email': 'orga.hackflow@example.test',
                    'first_name': 'Nadia',
                    'last_name': 'Belkacem',
                    'role': 'admin',
                },
            )
            if created:
                organizer.set_password('HackFlow2026!')
                organizer.save()
            self.stdout.write(self.style.WARNING(
                'Organisateur créé : orga.hackflow / HackFlow2026!'))

        # ------------------------------------------------------------------
        # Étudiants
        # ------------------------------------------------------------------
        students = list(
            User.objects.filter(
                role='student', username__startswith='demo.workshop'
            ).order_by('pk')[:4]
        )
        index = 1
        while len(students) < 4:
            username = f'demo.workshop{index}'
            index += 1
            if any(u.username == username for u in students):
                continue
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@example.test',
                    'first_name': 'Étudiant',
                    'last_name': f'Démo {index - 1}',
                    'role': 'student',
                    'specialty': 'Développeur Full-Stack',
                    'skills': ['Python', 'Django', 'Docker'],
                    'bio': 'Participant de démonstration HackFlow.',
                },
            )
            if created:
                user.set_password('HackFlow2026!')
                user.save()
            students.append(user)

        # ------------------------------------------------------------------
        # Ateliers passés (servent d'historique à l'IA de prédiction)
        # ------------------------------------------------------------------
        past_specs = [
            ('Git & GitHub pour hackathon', 'onsite', 'Salle B12', 3, 25, 22, 4.6),
            ('Déployer une API Django sur Render', 'online', '', 6, 40, 34, 4.4),
            ('Design Systems avec Figma', 'onsite', 'Salle A04', 9, 20, 19, 4.8),
            ('Introduction au prompt engineering', 'recorded', '', 12, 0, 55, 4.1),
            ('Pitcher son projet en 3 minutes', 'online', '', 15, 60, 41, 4.7),
        ]

        for title, mode, room, days_ago, capacity, attendees, rating in past_specs:
            starts = now - timedelta(days=days_ago, hours=2)
            workshop, _ = Workshop.objects.update_or_create(
                title=title,
                defaults={
                    'description': f"Atelier « {title} » — session de démonstration.",
                    'speaker_name': 'Intervenant HackFlow',
                    'speaker_company': 'HackFlow Partners',
                    'topic_tags': ['python', 'django', 'docker', 'git', 'design'],
                    'level': 'intermediate',
                    'mode': mode,
                    'room': room,
                    'meeting_url': 'https://meet.example.test/demo' if mode == 'online' else '',
                    'replay_url': 'https://videos.example.test/replay' if mode == 'recorded' else '',
                    'starts_at': starts,
                    'ends_at': starts + timedelta(hours=2),
                    'capacity': capacity,
                    'is_open': False,
                    'created_by': organizer,
                },
            )
            # Présences passées + certificats
            for position, student in enumerate(students):
                booking, _ = Booking.objects.update_or_create(
                    workshop=workshop,
                    user=student,
                    defaults={
                        'status': Booking.Status.ATTENDED,
                        'attended_at': starts + timedelta(hours=1),
                        'rating': int(rating) if position == 0 else None,
                    },
                )
                Certificate.objects.get_or_create(
                    workshop=workshop,
                    user=student,
                    defaults={'hours': Decimal('2.0')},
                )

        # ------------------------------------------------------------------
        # Ateliers à venir (3 modes)
        # ------------------------------------------------------------------
        upcoming_specs = [
            ('Kubernetes en pratique', 'onsite', 'Salle C01', 1, 3,
             'DevOps, Cloud, Kubernetes', ['kubernetes', 'devops', 'docker']),
            ('IA générative pour développeurs', 'online', '', 2, 50,
             'IA, LLM, Python', ['ia', 'llm', 'python']),
            ('Sécurité des applications web', 'onsite', 'Salle B07', 3, 25,
             'OWASP, Django, Sécurité', ['securite', 'django', 'owasp']),
            ('Replay : UX Research express', 'recorded', '', 4, 0,
             'UX, Figma, Recherche utilisateur', ['ux', 'figma', 'recherche']),
            ('Pitch final : convaincre le jury', 'online', '', 5, 80,
             'Pitch, Storytelling, Présentation', ['pitch', 'storytelling']),
        ]

        for title, mode, room, days_ahead, capacity, description, tags in upcoming_specs:
            starts = now + timedelta(days=days_ahead, hours=3)
            workshop, _ = Workshop.objects.update_or_create(
                title=title,
                defaults={
                    'description': description,
                    'speaker_name': 'Expert HackFlow',
                    'speaker_company': 'HackFlow Academy',
                    'topic_tags': tags,
                    'level': 'intermediate',
                    'mode': mode,
                    'room': room,
                    'meeting_url': 'https://meet.example.test/live' if mode == 'online' else '',
                    'replay_url': 'https://videos.example.test/ux-express' if mode == 'recorded' else '',
                    'available_until': now + timedelta(days=30) if mode == 'recorded' else None,
                    'starts_at': starts,
                    'ends_at': starts + timedelta(hours=2),
                    'capacity': capacity,
                    'is_open': True,
                    'created_by': organizer,
                },
            )

            # Réservations : le premier atelier est volontairement presque complet
            if title == 'Kubernetes en pratique':
                statuses = [
                    Booking.Status.CONFIRMED,
                    Booking.Status.CONFIRMED,
                    Booking.Status.CONFIRMED,
                    Booking.Status.WAITING,
                ]
            else:
                statuses = [Booking.Status.CONFIRMED, Booking.Status.CONFIRMED]

            for position, status in enumerate(statuses):
                student = students[position]
                Booking.objects.update_or_create(
                    workshop=workshop,
                    user=student,
                    defaults={
                        'status': status,
                        'seat_number': position + 1
                        if status == Booking.Status.CONFIRMED else None,
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            'Données de démonstration créées : 10 ateliers, réservations, '
            'certificats et badges.'))
