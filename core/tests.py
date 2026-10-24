import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse


class CustomErrorPageTests(TestCase):
    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_not_found_page_links_to_the_correct_dashboard_for_logged_in_role(self):
        for role, route in (
            ('student', 'student:dashboard'), ('mentor', 'mentor:dashboard'),
            ('admin', 'dashboard_admin:dashboard'),
        ):
            user = get_user_model().objects.create_user(username=f'error-{role}', role=role)
            self.client.force_login(user)
            response = self.client.get('/missing-page-for-test/')
            self.assertEqual(response.status_code, 404)
            self.assertTemplateUsed(response, '404.html')
            self.assertContains(response, reverse(route), status_code=404)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_forbidden_page_uses_custom_template_and_role_dashboard(self):
        student = get_user_model().objects.create_user(username='error-forbidden-student', role='student')
        self.client.force_login(student)
        response = self.client.get(reverse('mentor:dashboard'))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, reverse('student:dashboard'), status_code=403)


class ProductionHealthAndStorageTests(TestCase):
    def test_health_endpoint_returns_json_without_querying_database(self):
        with patch.object(connection, 'cursor', side_effect=AssertionError('health check queried the database')):
            response = self.client.get(reverse('healthz'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_private_storage_and_repository_paths_are_not_served_as_media(self):
        with tempfile.TemporaryDirectory(prefix='hackflow-private-path-test-') as temp_root:
            root = Path(temp_root)
            media_root = root / 'media'
            private_root = root / 'private_media'
            repository_root = root / 'repositories'
            media_root.mkdir()
            private_root.mkdir()
            repository_root.mkdir()
            (private_root / 'private-probe.txt').write_text('private', encoding='utf-8')
            (repository_root / 'private-probe.txt').write_text('private', encoding='utf-8')
            with override_settings(MEDIA_ROOT=media_root, PRIVATE_MEDIA_ROOT=private_root, REPOS_ROOT=repository_root):
                for url in (
                    '/media/private-probe.txt',
                    '/private_media/private-probe.txt',
                    '/.repository-data/private-probe.txt',
                    '/repositories/private-probe.txt',
                ):
                    with self.subTest(url=url):
                        self.assertEqual(self.client.get(url).status_code, 404)

    def test_production_settings_refuse_to_load_without_secret_key(self):
        project_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env['DJANGO_DEBUG'] = 'False'
        env['DJANGO_SECRET_KEY'] = ''
        code = (
            'import pathlib; original = pathlib.Path.is_file; '
            'pathlib.Path.is_file = lambda path: False if path.name == ".env" else original(path); '
            'import hackflow.settings'
        )
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=project_root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY must be set', result.stderr)
