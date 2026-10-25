"""Données de démonstration de l'espace mentor (idempotent : peut être relancé sans doublons).

    python manage.py seed_mentor

S'appuie sur ``seed_demo`` (module student) pour le hackathon, l'équipe EcoTrack et le mentor
marc.dubois, puis ajoute des mentors, des équipes, des demandes d'aide, des sessions,
des soumissions et des évaluations. Mot de passe des comptes créés : HackFlow2026!
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from mentor.models import (Criterion, EvaluationScore, MentorAssignment, MentorEvaluation, MentoringSession)
from student.models import Hackathon, MentorRequest, Milestone, Submission, Task, Team, TeamMembership

PASSWORD = 'HackFlow2026!'

MENTORS = [
    ('sarah.benali', 'Sarah', 'Benali', 'IA & Machine Learning', ['Python', 'LLM', 'Data']),
    ('thomas.vasseur', 'Thomas', 'Vasseur', 'DevOps, Docker & Cloud', ['Docker', 'CI/CD', 'AWS']),
    ('lea.rousseau', 'Léa', 'Rousseau', 'UX/UI Design & Figma', ['Figma', 'Design System', 'Accessibilité']),
]

# nom, catégorie, table, pitch, membres (username, prénom, nom, rôle), tâches (terminées, total)
TEAMS = [
    ('MediConnect', 'Santé & Bien-être', 'Table 08',
     "Plateforme d'orientation aux urgences basée sur un triage intelligent des symptômes.",
     [('ines.haddad', 'Inès', 'Haddad', 'Capitaine & Back-End'), ('noah.petit', 'Noah', 'Petit', 'Front-End'),
      ('sofia.garcia', 'Sofia', 'Garcia', 'Data')], (5, 12)),
    ('FinEd', 'FinTech Éducative', 'Table 21',
     "Micro-épargne ludique pour étudiants avec simulation d'investissement éthique.",
     [('adam.cherif', 'Adam', 'Chérif', 'Capitaine & Full-Stack'), ('lina.moreau', 'Lina', 'Moreau', 'UX/UI')],
     (7, 12)),
    ('SafeCity', 'Smart City & Sécurité', 'Table 05',
     "Application citoyenne de signalement d'incivilités et d'entraide locale.",
     [('yanis.robert', 'Yanis', 'Robert', 'Capitaine & Mobile'), ('emma.lefevre', 'Emma', 'Lefèvre', 'Back-End'),
      ('karim.benamar', 'Karim', 'Benamar', 'DevOps')], (4, 10)),
    ('StudyBuddy AI', 'Éducation & IA', 'Table 19',
     "Assistant d'apprentissage adaptatif qui synthétise les cours magistraux.",
     [('chloe.martin', 'Chloé', 'Martin', 'Capitaine & IA'), ('hugo.dupont', 'Hugo', 'Dupont', 'Back-End')],
     (9, 11)),
]

# équipe, sujet, catégorie, urgence, description
PENDING_REQUESTS = [
    ('MediConnect', 'Le conteneur Docker plante au démarrage', 'DevOps, Docker & Cloud Deployment', 'blocking',
     "Depuis ce matin notre image ne démarre plus : KeyError DJANGO_SECRET_KEY. Les variables d'environnement "
     "ne semblent pas injectées dans le conteneur et la démo est cet après-midi."),
    ('FinEd', 'Requête de simulation trop lente', 'Back-End Development & Databases', 'important',
     "La projection sur 5 ans prend plus de 4 secondes sur 10 000 transactions simulées. On fait une requête "
     "par mois dans une boucle Python. Ça fonctionne mais c'est lent."),
    ('SafeCity', 'Flouter automatiquement les visages sur les photos', 'AI, LLMs & Machine Learning', 'normal',
     "Nous voulons intégrer un modèle de vision pour flouter visages et plaques d'immatriculation avant "
     "publication. Quel modèle léger conseillez-vous ?"),
    ('StudyBuddy AI', 'Structure du pitch de 3 minutes', 'Pitch & Presentation Structure', 'normal',
     "Nous avons trop de contenu pour 3 minutes. Dans quel ordre présenter problème, solution, démo et "
     "modèle économique ?"),
    ('SafeCity', 'Menu mobile impossible à fermer', 'UI/UX Design & User Experience', 'important',
     "Sur téléphone, le menu recouvre tout l'écran et le bouton de fermeture est hors de portée. On peut "
     "contourner en rechargeant la page mais les testeurs sont perdus."),
]


class Command(BaseCommand):
    help = "Crée des données de démonstration pour l'espace mentor (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command('seed_demo', stdout=self.stdout)
        User = get_user_model()
        now = timezone.now()
        hackathon = Hackathon.objects.filter(name='HackFlow', edition='2026 Edition').first()
        marc = User.objects.get(username='marc.dubois')
        # seed_demo crée marc.dubois sans mot de passe : on en définit un seulement s'il n'en a pas.
        if not marc.password or not marc.has_usable_password():
            marc.set_password(PASSWORD)
            marc.save(update_fields=['password'])

        mentors = {'marc.dubois': marc}
        for username, first, last, specialty, skills in MENTORS:
            mentors[username] = self._user(username, first, last, 'mentor', specialty=specialty, skills=skills)

        teams = {'EcoTrack': Team.objects.get(hackathon=hackathon, name='EcoTrack')}
        for name, category, table, pitch, members, (done, total) in TEAMS:
            users = [self._user(u, f, l, 'student') for u, f, l, _role in members]
            team, _ = Team.objects.get_or_create(hackathon=hackathon, name=name, defaults={
                'category': category, 'table_number': table, 'room': 'Halle Informatique', 'captain': users[0],
                'project_name': name, 'project_pitch': pitch, 'description': pitch})
            for user, (_u, _f, _l, role) in zip(users, members):
                TeamMembership.objects.get_or_create(team=team, user=user, defaults={'role': role})
            for index in range(total):
                Task.objects.get_or_create(team=team, title=f'Tâche {index + 1} — {name}', defaults={
                    'status': 'done' if index < done else 'in_progress', 'category': 'Backend',
                    'assignee': users[index % len(users)]})
            teams[name] = team

        for team_name, subject, category, urgency, description in PENDING_REQUESTS:
            team = teams[team_name]
            MentorRequest.objects.get_or_create(team=team, subject=subject, defaults={
                'student': team.captain, 'category': category, 'urgency': urgency, 'description': description})

        # Ticket résolu par Marc (onglet « Mes tickets résolus »).
        resolved, _ = MentorRequest.objects.get_or_create(team=teams['FinEd'], subject='Erreur CSRF sur le formulaire',
                                                          defaults={
            'student': teams['FinEd'].captain, 'mentor': marc, 'category': 'Back-End Development & Databases',
            'urgency': 'blocking', 'status': MentorRequest.Status.RESOLVED,
            'description': "Le formulaire d'inscription renvoie 403 CSRF verification failed.",
            'resolution_note': "Ajout de {% csrf_token %} dans le formulaire et de l'origine Render dans "
                               "CSRF_TRUSTED_ORIGINS."})

        for team_name, source in (('EcoTrack', MentorAssignment.Source.AUTO),
                                  ('FinEd', MentorAssignment.Source.AUTO),
                                  ('MediConnect', MentorAssignment.Source.MENTOR)):
            MentorAssignment.follow(marc, teams[team_name], source)
        MentorAssignment.follow(mentors['sarah.benali'], teams['StudyBuddy AI'], MentorAssignment.Source.MENTOR)

        today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        sessions = [
            ('EcoTrack', "Point d'étape sur l'architecture API", today + timedelta(hours=23), 30,
             MentoringSession.Status.CONFIRMED, None),
            ('MediConnect', 'Revue de la configuration Docker', now + timedelta(days=1, hours=2), 45,
             MentoringSession.Status.PLANNED, None),
            ('FinEd', 'Débogage de la protection CSRF', now - timedelta(hours=5), 30,
             MentoringSession.Status.DONE, resolved),
            ('EcoTrack', 'Préparation des questions du jury', now - timedelta(hours=2), 30,
             MentoringSession.Status.CANCELLED, None),
        ]
        for team_name, topic, start, minutes, status, help_request in sessions:
            team = teams[team_name]
            MentoringSession.objects.get_or_create(mentor=marc, team=team, topic=topic, defaults={
                'starts_at': start, 'ends_at': start + timedelta(minutes=minutes), 'status': status,
                'location': f'{team.table_number}, {team.room}', 'help_request': help_request})

        milestone = (Milestone.objects.filter(hackathon=hackathon, title__startswith='Milestone 1').first()
                     or Milestone.objects.filter(hackathon=hackathon).order_by('order').first())
        if milestone is None:
            raise CommandError('Aucun jalon trouvé : lancez d’abord seed_demo.')
        submissions = {}
        for team_name in ('EcoTrack', 'FinEd', 'StudyBuddy AI', 'SafeCity'):
            team = teams[team_name]
            submissions[team_name], _ = Submission.objects.get_or_create(team=team, milestone=milestone, defaults={
                'project_name': team.project_name or team.name, 'status': Submission.Status.SUBMITTED,
                'description': team.project_pitch, 'project_summary': team.project_pitch,
                'submitted_by': team.captain, 'submitted_at': now - timedelta(hours=3)})

        criteria = list(Criterion.for_scope(Criterion.Scope.MENTOR))
        evaluations = [
            ('marc.dubois', 'EcoTrack', (4.5, 4, 4, 3.5), MentorEvaluation.PitchReadiness.ON_TRACK, True,
             "Vision produit claire et architecture saine. Simplifiez l'onboarding avant la démo jury."),
            ('marc.dubois', 'FinEd', (3.5, 3, 4, 3), MentorEvaluation.PitchReadiness.NOT_READY, False,
             "Bonne idée, mais la simulation est encore lente : optimisez les requêtes avant le pitch."),
            ('sarah.benali', 'StudyBuddy AI', (5, 4.5, 4, 4.5), MentorEvaluation.PitchReadiness.READY, True,
             "Pipeline RAG solide ; mettez en avant le benchmark comparatif à l'oral."),
        ]
        for mentor_name, team_name, scores, readiness, shared, comment in evaluations:
            evaluation, created = MentorEvaluation.objects.get_or_create(
                mentor=mentors[mentor_name], submission=submissions[team_name],
                defaults={'pitch_readiness': readiness, 'general_comment': comment})
            if created:
                for criterion, value in zip(criteria, scores):
                    EvaluationScore.objects.create(evaluation=evaluation, criterion=criterion, score=Decimal(str(value)))
                if shared:
                    evaluation.share()

        self.stdout.write(self.style.SUCCESS(
            f'Données mentor prêtes : {len(mentors)} mentors, {len(teams)} équipes, '
            f'{MentorRequest.objects.filter(status=MentorRequest.Status.PENDING).count()} demandes en attente. '
            f'Connexion : marc.dubois / {PASSWORD}'))

    def _user(self, username, first, last, role, **extra):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={
            'first_name': first, 'last_name': last, 'role': role,
            'email': f'{username}@{"hackflow.fr" if role == "mentor" else "etu.univ.fr"}', **extra})
        if created:
            user.set_password(PASSWORD)
            user.save(update_fields=['password'])
        elif user.role != role:
            raise CommandError(f'{username} existe déjà avec un autre rôle ; aucune donnée modifiée.')
        return user
