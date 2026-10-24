from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Hackathon, Team, TeamMembership


class MalformedStudentPostTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(username='robust-student', password='pass', role='student')
        now = timezone.now()
        hackathon = Hackathon.objects.create(name='Robustness', starts_at=now, ends_at=now + timedelta(days=1))
        self.team = Team.objects.create(hackathon=hackathon, name='Robust Team', captain=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student, role='Captain')
        self.client.force_login(self.student)

    def test_malformed_and_missing_ids_do_not_raise_server_errors(self):
        for payload in (
            {'action': 'edit_task', 'task_id': 'not-an-id'},
            {'action': 'delete', 'task_id': ''},
            {'action': 'remove_member', 'member_id': 'not-an-id'},
            {'action': 'transfer_captain'},
            {'action': 'cancel_invitation', 'invitation_id': 'invalid'},
            {'action': 'approve_leave_request', 'leave_request_id': 'invalid'},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(reverse('student:tasks_kanban') if 'task_id' in payload
                                            else reverse('student:team_detail'), payload)
                self.assertNotEqual(response.status_code, 500)

    def test_malformed_milestone_ids_fall_back_without_server_error(self):
        response = self.client.get(reverse('student:project_submission'), {'milestone': 'not-an-id'})
        self.assertNotEqual(response.status_code, 500)
        self.assertIn(response.status_code, (200, 302))

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_unavailable_task_queue_returns_a_failed_job_instead_of_500(self):
        response = self.client.post(reverse('student:tasks_kanban'), {
            'action': 'create_ai_task_job', 'prompt': 'Add password reset support', 'sprint': '',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')
