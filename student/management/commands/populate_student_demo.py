from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from student.models import (
    Announcement,
    DirectMessage,
    MentorRequest,
    Milestone,
    Notification,
    Resource,
    Sprint,
    Submission,
    Task,
    Team,
    TeamMembership,
)


DEMO_STUDENTS = [
    {
        'username': 'demo.amira', 'first_name': 'Amira', 'last_name': 'Ben Salem',
        'email': 'amira.bensalem@example.test', 'specialty': 'Front-End Developer',
        'skills': ['React / TypeScript', 'UI/UX & Figma'],
    },
    {
        'username': 'demo.youssef', 'first_name': 'Youssef', 'last_name': 'Trabelsi',
        'email': 'youssef.trabelsi@example.test', 'specialty': 'Back-End Developer',
        'skills': ['Python / Django', 'PostgreSQL'],
    },
    {
        'username': 'demo.lina', 'first_name': 'Lina', 'last_name': 'Haddad',
        'email': 'lina.haddad@example.test', 'specialty': 'Product Designer',
        'skills': ['UI/UX & Figma', 'Pitch & Business Model'],
    },
]

UNASSIGNED_DEMO_STUDENTS = [
    {
        'username': 'demo.noor', 'first_name': 'Noor', 'last_name': 'Gharbi',
        'email': 'noor.gharbi@example.test', 'specialty': 'Data Science / AI',
        'skills': ['Python', 'Machine Learning'],
        'bio': 'Looking for a team building a useful AI project.',
    },
    {
        'username': 'demo.karim', 'first_name': 'Karim', 'last_name': 'Ayari',
        'email': 'karim.ayari@example.test', 'specialty': 'Back-End Development',
        'skills': ['Django', 'PostgreSQL', 'REST APIs'],
        'bio': 'Available to join a team and build backend features.',
    },
    {
        'username': 'demo.salma', 'first_name': 'Salma', 'last_name': 'Jaziri',
        'email': 'salma.jaziri@example.test', 'specialty': 'UI/UX Design & Product',
        'skills': ['Figma', 'Prototyping', 'User Research'],
        'bio': 'Searching for a team that needs product design support.',
    },
]


class Command(BaseCommand):
    help = 'Add a small, reusable set of student demo records to a team.'

    def add_arguments(self, parser):
        parser.add_argument('--team', help='Team name to populate. Defaults to the least populated team.')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        demo_usernames = [student['username'] for student in DEMO_STUDENTS]
        team = Team.objects.filter(memberships__user__username__in=demo_usernames).distinct().first()
        if not team and options.get('team'):
            team = Team.objects.filter(name=options['team']).select_related('hackathon', 'captain').first()
        if not team:
            team = Team.objects.annotate(member_total=Count('memberships')) \
                .select_related('hackathon', 'captain').order_by('member_total', 'created_at').first()
        if not team:
            raise CommandError('Create a team before populating student demo data.')
        if team.max_members < 1:
            raise CommandError('The selected team has no member slots.')

        for data in DEMO_STUDENTS:
            user = User.objects.filter(username=data['username']).first()
            if user and user.role != 'student':
                raise CommandError(f"Username {data['username']} is already used by a non-student account.")
            if not user:
                user = User.objects.create_user(
                    username=data['username'], email=data['email'], password='HackFlow2026!',
                    first_name=data['first_name'], last_name=data['last_name'], role='student',
                    school='HackFlow Demo University', study_level='Master 1',
                    specialty=data['specialty'], skills=data['skills'],
                    bio=f"{data['specialty']} helping build {team.name}.",
                )
            if team.places_left or team.memberships.filter(user=user).exists():
                TeamMembership.objects.get_or_create(
                    team=team, user=user,
                    defaults={'role': data['specialty']},
                )

        for data in UNASSIGNED_DEMO_STUDENTS:
            user = User.objects.filter(username=data['username']).first()
            if user and user.role != 'student':
                raise CommandError(f"Username {data['username']} is already used by a non-student account.")
            if not user:
                User.objects.create_user(
                    username=data['username'], email=data['email'], password='HackFlow2026!',
                    first_name=data['first_name'], last_name=data['last_name'], role='student',
                    school='HackFlow Demo University', study_level='Master 1',
                    specialty=data['specialty'], skills=data['skills'], bio=data['bio'],
                )

        team_members = list(team.memberships.select_related('user').order_by('pk'))
        captain = team.captain or (team_members[0].user if team_members else None)
        if not captain:
            raise CommandError('The selected team has no member who can own its demo records.')
        if team.captain_id is None:
            team.captain = captain
            team.save(update_fields=['captain'])

        # Keep each sample collection small and safe to run repeatedly.
        if not team.project_name:
            team.project_name = f'{team.name} Workspace'
        if not team.project_pitch:
            team.project_pitch = 'A collaborative workspace for organizing student projects and tasks.'
        if not team.description:
            team.description = team.project_pitch
        team.save(update_fields=['project_name', 'project_pitch', 'description'])

        now = timezone.now()
        sprint = team.sprints.filter(status=Sprint.Status.ACTIVE).first()
        if not sprint:
            sprint = Sprint.objects.create(
                team=team, name='Demo Sprint', goal='Complete the next team workspace improvements.',
                starts_at=now, ends_at=team.hackathon.ends_at if team.hackathon.ends_at > now else now + timedelta(days=7),
                status=Sprint.Status.ACTIVE,
            )

        assignees = [member.user for member in team_members if member.user_id != captain.pk] or [captain]
        task_examples = [
            ('Build the team dashboard summary', 'Frontend', Task.Status.IN_PROGRESS, assignees[0]),
            ('Add task filters and search', 'Backend', Task.Status.TODO, assignees[1 % len(assignees)]),
            ('Review the mobile layout', 'Design & UX', Task.Status.REVIEW, assignees[2 % len(assignees)]),
            ('Write project setup instructions', 'Documentation', Task.Status.DONE, captain),
        ]
        task_count = team.tasks.count()
        for title, category, status, assignee in task_examples:
            if task_count >= 4:
                break
            task, was_created = Task.objects.get_or_create(
                team=team, title=title,
                defaults={
                    'sprint': sprint, 'category': category, 'status': status,
                    'priority': Task.Priority.NORMAL, 'assignee': assignee,
                    'deadline': now + timedelta(days=2),
                },
            )
            if was_created:
                task_count += 1

        # These were illustrative links, not team-owned project links. Remove only
        # those known placeholders; teams add their actual links in the workspace.
        Resource.objects.filter(team=team, url__in=[
            'https://github.com/example/student-team-project',
            'https://www.figma.com/community',
            'https://example.test/demo',
        ]).delete()

        if team.hackathon.announcements.count() < 3:
            Announcement.objects.get_or_create(
                hackathon=team.hackathon, title='Demo day preparation starts today',
                defaults={'author': 'HackFlow Staff', 'category': 'Updates', 'published_at': now},
            )

        mentor = User.objects.filter(role='mentor').first()
        mentor_requests = [
            ('Review our API structure', 'Technical / Back-end', 'important'),
            ('Feedback on the project prototype', 'Product / Design', 'normal'),
            ('Help with deployment configuration', 'DevOps / Cloud', 'blocking'),
        ]
        for subject, category, urgency in mentor_requests:
            if team.mentor_requests.count() >= 3:
                break
            MentorRequest.objects.get_or_create(
                team=team, student=captain, subject=subject,
                defaults={
                    'mentor': mentor, 'category': category,
                    'description': f'Demo request for the {team.name} team.',
                    'urgency': urgency, 'status': MentorRequest.Status.PENDING,
                },
            )

        members = list(team.memberships.select_related('user').exclude(user=captain).order_by('pk')[:3])
        demo_messages = []
        if members:
            demo_messages.append((captain, members[0].user, 'I have added the first tasks to our team board.'))
            demo_messages.append((members[0].user, captain, 'Thanks! I will start with the dashboard task.'))
        if len(members) > 1:
            demo_messages.append((captain, members[1].user, 'Could you review the API task when you have time?'))
        for sender, recipient, body in demo_messages:
            DirectMessage.objects.get_or_create(sender=sender, recipient=recipient, body=body)

        notification_examples = [
            ('Welcome to your team', f'Your team workspace {team.name} is ready.'),
            ('New sprint tasks', 'The team has added tasks to the sprint board.'),
            ('Demo data added', 'Sample teammates and project records are available.'),
        ]
        for title, message in notification_examples:
            if Notification.objects.filter(user=captain).count() >= 3:
                break
            Notification.objects.get_or_create(
                user=captain, title=title,
                defaults={'message': message, 'icon': 'bi-info-circle-fill'},
            )

        milestone = team.hackathon.milestones.order_by('due_at').last()
        if milestone:
            Submission.objects.get_or_create(
                team=team, milestone=milestone,
                defaults={
                    'project_name': team.project_name,
                    'category': team.category,
                    'description': team.project_pitch,
                    'submitted_by': captain,
                    'status': Submission.Status.DRAFT,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Demo data is ready for {team.name}: {team.memberships.count()} members, "
            f"{team.tasks.count()} tasks, {team.resources.count()} resources, "
            f"{team.mentor_requests.count()} mentor requests."
        ))
