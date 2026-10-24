from datetime import timedelta
import json
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
