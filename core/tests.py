from datetime import timedelta
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .views import csrf_failure, error_page, healthz
from student.models import Hackathon, HackathonRegistration, Team, TeamMembership


class CoreViewCoverageTests(TestCase):
    def test_en_and_ar_catalogs_have_no_empty_or_fuzzy_translations(self):
        for language in ('en', 'ar'):
            catalog = Path(__file__).resolve().parent.parent / 'locale' / language / 'LC_MESSAGES' / 'django.po'
            entries = []
            current = {}
            active = None
            for raw_line in catalog.read_text(encoding='utf-8').splitlines():
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    if current:
                        entries.append(current)
                        current = {}
                    active = None
                elif line.startswith('msgid '):
                    active = 'msgid'
                    current[active] = ast.literal_eval(line[6:])
                elif line.startswith('msgstr '):
                    active = 'msgstr'
                    current[active] = ast.literal_eval(line[7:])
                elif line.startswith('"') and active:
                    current[active] += ast.literal_eval(line)
            if current:
                entries.append(current)

            messages = [entry for entry in entries if entry.get('msgid')]
            self.assertTrue(messages, f'{language} catalog has no messages')
            self.assertFalse([entry['msgid'] for entry in messages if not entry.get('msgstr')])
            self.assertNotIn('#, fuzzy', catalog.read_text(encoding='utf-8'))
            if language == 'ar':
                unchanged = [entry['msgid'] for entry in messages if entry['msgid'] == entry.get('msgstr')]
                self.assertFalse(unchanged, f'Arabic translations left as source text: {unchanged}')

    def test_public_dashboards_follow_fr_en_ar_language(self):
        dashboard_routes = (
            ('student', 'student:dashboard', 'Tableau de bord', 'Dashboard', 'لوحة التحكم'),
            ('mentor', 'mentor:dashboard', 'Tableau de bord', 'Dashboard', 'لوحة التحكم'),
            ('admin', 'dashboard_admin:dashboard', 'Cockpit organisateur', 'Organizer cockpit', 'لوحة تحكم المنظم'),
        )
        for role, route, french_label, english_label, arabic_label in dashboard_routes:
            user = get_user_model().objects.create_user(
                username=f'i18n-{role}', password='test-password', role=role, is_active=True,
            )
            self.client.force_login(user)
            for language in ('fr', 'en', 'ar'):
                response = self.client.get(reverse(route), HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(response.status_code, 200, f'{route} failed in {language}')
                self.assertEqual(response.wsgi_request.LANGUAGE_CODE, language)
                page = response.content.decode('utf-8')
                if language == 'ar':
                    self.assertTrue('<html lang="ar" dir="rtl"' in page, f'{route} missing Arabic RTL document in {language}')
                    self.assertTrue(arabic_label in page, f'{route} missing Arabic navigation label in {language}')
                elif language == 'en':
                    self.assertTrue('<html lang="en" dir="ltr"' in page, f'{route} missing English LTR document in {language}')
                    self.assertTrue(english_label in page, f'{route} missing English navigation label in {language}')
                else:
                    self.assertTrue('<html lang="fr" dir="ltr"' in page, f'{route} missing French LTR document in {language}')
                    self.assertTrue(french_label in page, f'{route} missing French navigation label in {language}')
            self.client.logout()

    def test_public_copy_uses_selected_english_and_arabic_catalogs(self):
        english_home = self.client.get('/', HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(english_home.status_code, 200)
        self.assertContains(english_home, 'Join the Hackathon')
        self.assertContains(english_home, 'Frequently asked questions')
        self.assertNotContains(english_home, 'Participer au Hackathon')

        english_login = self.client.get(reverse('accounts:login'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(english_login, 'Welcome back to HackFlow')
        english_signup = self.client.get(reverse('accounts:register'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(english_signup, 'I am a student')

        arabic_home = self.client.get('/', HTTP_ACCEPT_LANGUAGE='ar')
        self.assertContains(arabic_home, 'شارك في الهاكاثون')
        self.assertContains(arabic_home, 'الأسئلة الشائعة')
        self.assertNotContains(arabic_home, 'Participer au Hackathon')
        self.assertContains(arabic_home, '<html lang="ar" dir="rtl"', html=False)

        arabic_login = self.client.get(reverse('accounts:login'), HTTP_ACCEPT_LANGUAGE='ar')
        self.assertContains(arabic_login, 'مرحباً بعودتك إلى HackFlow')
        arabic_signup = self.client.get(reverse('accounts:register'), HTTP_ACCEPT_LANGUAGE='ar')
        self.assertContains(arabic_signup, 'أنا طالب')

    def test_language_switcher_persists_arabic_and_sets_rtl_document(self):
        french_response = self.client.get('/')
        self.assertContains(french_response, 'bootstrap.min.css')
        self.assertContains(
            french_response,
            'integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"',
        )

        switch_response = self.client.post(reverse('set_language'), {
            'language': 'ar', 'next': '/',
        })

        self.assertEqual(switch_response.status_code, 302)
        self.assertEqual(switch_response.cookies['django_language'].value, 'ar')
        response = self.client.get('/')
        self.assertContains(response, '<html lang="ar" dir="rtl"', html=False)
        self.assertContains(response, 'href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"')
        self.assertContains(response, 'bootstrap.rtl.min.css')
        self.assertContains(
            response,
            'integrity="sha384-dpuaG1suU0eT09tx5plTaGMLBsfDLzUCCUXOY2j/LSvXYuG6Bqs43ALlhIqAJVRb"',
        )
        self.assertContains(response, 'integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"')

    def test_health_endpoint_is_database_independent_json(self):
        response = healthz(RequestFactory().get('/healthz/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'ok'})

    def test_csrf_failure_keeps_only_safe_same_host_referers(self):
        factory = RequestFactory()
        safe = factory.post('/submit/', HTTP_HOST='localhost', HTTP_REFERER='https://localhost/form/')
        with patch('core.views.render', return_value=HttpResponse(status=403)) as render_mock:
            safe_response = csrf_failure(safe, 'expired')
        self.assertEqual(safe_response.status_code, 403)
        self.assertIn('no-store', safe_response['Cache-Control'])
        self.assertEqual(render_mock.call_args.args[2]['retry_url'], 'https://localhost/form/')

        unsafe = factory.post('/submit/', HTTP_HOST='localhost', HTTP_REFERER='https://evil.test/phish')
        with patch('core.views.render', return_value=HttpResponse(status=403)) as render_mock:
            unsafe_response = csrf_failure(unsafe, 'expired')
        self.assertEqual(unsafe_response.status_code, 403)
        self.assertEqual(render_mock.call_args.args[2]['retry_url'], reverse('core:landing'))

    def test_error_page_selects_layout_from_user_role(self):
        request = RequestFactory().get('/missing/')
        for role, layout, destination in (
            ('student', 'layouts/base_student.html', 'student:dashboard'),
            ('mentor', 'layouts/base_mentor.html', 'mentor:dashboard'),
            ('admin', 'layouts/base_admin.html', 'dashboard_admin:dashboard'),
            ('unknown', 'layouts/base_public.html', 'core:landing'),
        ):
            request.user = SimpleNamespace(role=role)
            with patch('core.views.render', return_value=HttpResponse(status=404)) as render_mock:
                response = error_page(request, status=404)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(render_mock.call_args.args[1], '404.html')
            self.assertEqual(render_mock.call_args.args[2]['layout_template'], layout)
            self.assertEqual(render_mock.call_args.args[2]['dashboard_url'], destination)

    def test_landing_without_event_and_with_registered_event(self):
        response = self.client.get(reverse('core:landing'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['event_state'], 'none')

        now = timezone.now()
        event = Hackathon.objects.create(
            name='Coverage Hackathon', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1), is_active=True,
        )
        student = get_user_model().objects.create_user(
            username='coverage-student', role='student', is_active=True,
            skills=['Python'], preferred_roles=['developer'],
        )
        mentor = get_user_model().objects.create_user(
            username='coverage-mentor', role='mentor', is_active=True,
        )
        HackathonRegistration.objects.create(hackathon=event, user=student)
        team = Team.objects.create(hackathon=event, name='Coverage Team', max_members=3, category='AI')
        TeamMembership.objects.create(team=team, user=student)

        response = self.client.get(reverse('core:landing'))
        self.assertEqual(response.context['event_state'], 'live')
        self.assertEqual(response.context['participants_count'], 1)
        self.assertEqual(response.context['profiled_count'], 1)
        self.assertEqual(response.context['stats'][2]['value'], '1')
        self.assertEqual(response.context['featured_team']['name'], 'Coverage Team')

    def test_landing_uses_latest_inactive_event_and_event_state(self):
        now = timezone.now()
        event = Hackathon.objects.create(
            name='Past Event', starts_at=now - timedelta(days=3),
            ends_at=now - timedelta(days=2), is_active=False,
        )
        response = self.client.get(reverse('core:landing'))
        self.assertEqual(response.context['hackathon'], event)
        self.assertEqual(response.context['event_state'], 'ended')
