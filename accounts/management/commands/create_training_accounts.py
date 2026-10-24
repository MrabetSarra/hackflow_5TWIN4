import csv
import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Create synthetic student and mentor accounts and export one-time credentials locally.'

    def add_arguments(self, parser):
        parser.add_argument('--students', type=int, default=10)
        parser.add_argument('--mentors', type=int, default=10)
        parser.add_argument('--credentials', default='private_media/training_accounts_credentials.csv')

    @transaction.atomic
    def handle(self, *args, **options):
        student_count, mentor_count = options['students'], options['mentors']
        if student_count < 0 or mentor_count < 0 or student_count + mentor_count == 0:
            raise CommandError('Provide a positive total and non-negative role counts.')
        User = get_user_model()
        created = []
        student_skills = [
            ['Python / Django', 'PostgreSQL'], ['React / TypeScript', 'UI/UX & Figma'],
            ['FastAPI', 'DevOps & Docker'], ['IA & Machine Learning', 'Python / Django'],
            ['Flutter / Mobile', 'React / TypeScript'],
        ]
        for role, count in (('student', student_count), ('mentor', mentor_count)):
            for number in range(1, count + 1):
                username = f'demo.{role}{number:02d}'
                email = f'{role}{number:02d}@example.test'
                if User.objects.filter(username=username).exists():
                    self.stdout.write(self.style.WARNING(f'Skipped existing account: {username}'))
                    continue
                if User.objects.filter(email__iexact=email).exists():
                    raise CommandError(f'Email already in use: {email}; no account was created.')
                password = secrets.token_urlsafe(18)
                if role == 'student':
                    user = User(
                        username=username, email=email, role=role,
                        first_name=f'Student {number:02d}', last_name='HackFlow',
                        school='HackFlow Training Cohort', study_level='Master 1',
                        specialty='Computer Science', skills=student_skills[(number - 1) % len(student_skills)],
                    )
                else:
                    specialties = ['Python & Django', 'Frontend & UX', 'Cloud & DevOps', 'Data & AI', 'Mobile Development']
                    user = User(
                        username=username, email=email, role=role,
                        first_name=f'Mentor {number:02d}', last_name='HackFlow',
                        school='HackFlow Training Cohort', specialty=specialties[(number - 1) % len(specialties)],
                    )
                user.set_password(password)
                user.save()
                created.append((username, email, role, password))

        target = Path(options['credentials'])
        if not target.is_absolute():
            target = Path(settings.BASE_DIR) / target
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['username', 'email', 'role', 'temporary_password'])
            writer.writerows(created)
        self.stdout.write(self.style.SUCCESS(
            f'Created {len(created)} accounts ({sum(row[2] == "student" for row in created)} students, '
            f'{sum(row[2] == "mentor" for row in created)} mentors). Credentials: {target}'
        ))
        self.stdout.write('These synthetic accounts use example.test email addresses; email delivery is disabled for them.')
