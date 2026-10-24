import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase


class EnsureAdminCommandTests(TestCase):
    def test_missing_variables_skip_creation(self):
        with patch.dict(os.environ, {}, clear=True):
            call_command('ensure_admin')
        self.assertFalse(get_user_model().objects.exists())

    def test_creates_configured_admin_and_is_idempotent(self):
        settings = {
            'DJANGO_SUPERUSER_USERNAME': 'configured-admin',
            'DJANGO_SUPERUSER_EMAIL': 'configured-admin@example.test',
            'DJANGO_SUPERUSER_PASSWORD': 'secret-password-not-printed',
        }
        with patch.dict(os.environ, settings, clear=True):
            call_command('ensure_admin')
            call_command('ensure_admin')

        users = get_user_model().objects.filter(username='configured-admin')
        self.assertEqual(users.count(), 1)
        admin = users.get()
        self.assertEqual(admin.role, 'admin')
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password(settings['DJANGO_SUPERUSER_PASSWORD']))

    def test_refuses_to_promote_existing_non_admin_account(self):
        User = get_user_model()
        User.objects.create_user(
            username='configured-admin', email='old@example.test', password='old-password', role='student',
        )
        settings = {
            'DJANGO_SUPERUSER_USERNAME': 'configured-admin',
            'DJANGO_SUPERUSER_EMAIL': 'configured-admin@example.test',
            'DJANGO_SUPERUSER_PASSWORD': 'new-password',
        }
        with patch.dict(os.environ, settings, clear=True):
            with self.assertRaises(CommandError):
                call_command('ensure_admin')

        user = User.objects.get(username='configured-admin')
        self.assertEqual(user.role, 'student')
        self.assertTrue(user.check_password('old-password'))
