import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create the configured Django administrator once, if all credentials are provided.'

    def handle(self, *args, **options):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', '').strip()
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')

        missing = [
            name for name, value in (
                ('DJANGO_SUPERUSER_USERNAME', username),
                ('DJANGO_SUPERUSER_EMAIL', email),
                ('DJANGO_SUPERUSER_PASSWORD', password),
            ) if not value
        ]
        if missing:
            self.stdout.write(self.style.WARNING(
                'Administrator creation skipped; set all DJANGO_SUPERUSER_* variables.'
            ))
            return

        User = get_user_model()
        existing = User.objects.filter(username=username).first()
        if existing:
            if existing.role == 'admin' and existing.is_staff and existing.is_superuser:
                self.stdout.write(self.style.SUCCESS('Configured administrator already exists.'))
                return
            raise CommandError(
                'The configured administrator username already belongs to a non-admin account; '
                'no account data was changed.'
            )

        if User.objects.filter(email=email).exists():
            raise CommandError(
                'The configured administrator email already belongs to another account; '
                'no account data was changed.'
            )

        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
            role='admin',
        )
        self.stdout.write(self.style.SUCCESS('Configured administrator created.'))
