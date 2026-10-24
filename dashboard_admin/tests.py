from datetime import timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard_admin.copilot import CopilotError, ask_copilot, build_hackathon_snapshot
from student.models import Announcement, Hackathon, HackathonRegistration, Team
from student.templatetags.announcement_format import announcement_markdown


class AnnouncementManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username='organizer', password='test-pass', role='organization')
        self.student = User.objects.create_user(username='participant', password='test-pass', role='student')
        self.mentor = User.objects.create_user(username='mentor', password='test-pass', role='mentor')
        now = timezone.now()
        self.hackathon = Hackathon.objects.create(
            name='HackFlow Test', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2), is_active=True,
        )
        self.client.force_login(self.admin)
        self.announcements_url = reverse('dashboard_admin:announcements')

    def post_announcement(self, **overrides):
        data = {
            'title': 'Presentation venue updated',
            'category': 'Logistics',
            'audience': Announcement.Audience.ALL,
            'priority': Announcement.Priority.INFO,
            'body': 'The room is now **B12**.',
            'submit_action': 'publish',
        }
        data.update(overrides)
        return self.client.post(self.announcements_url, data)

    def test_publish_stores_selected_audience_and_priority(self):
        response = self.post_announcement(audience=Announcement.Audience.MENTORS,
                                          priority=Announcement.Priority.IMPORTANT)
        self.assertRedirects(response, self.announcements_url)
        announcement = Announcement.objects.get()
        self.assertFalse(announcement.is_draft)
        self.assertEqual(announcement.audience, Announcement.Audience.MENTORS)
        self.assertEqual(announcement.priority, Announcement.Priority.IMPORTANT)

    def test_draft_can_be_saved_without_a_message_and_is_not_delivered(self):
        response = self.post_announcement(title='Working notes', body='', submit_action='draft')
        self.assertRedirects(response, self.announcements_url)
        draft = Announcement.objects.get()
        self.assertTrue(draft.is_draft)
        self.assertContains(self.client.get(self.announcements_url), 'Working notes')

    def test_publishing_requires_a_title_and_message(self):
        response = self.post_announcement(title='   ', body='')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Announcement.objects.exists())
        self.assertContains(response, 'Ajoutez le contenu de votre annonce.')

    def test_scheduled_announcement_is_not_shown_before_its_time(self):
        scheduled_at = timezone.localtime(timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        response = self.post_announcement(scheduled_at=scheduled_at)
        self.assertRedirects(response, self.announcements_url)
        announcement = Announcement.objects.get()
        self.assertTrue(announcement.is_scheduled)
        self.client.force_login(self.student)
        dashboard = self.client.get(reverse('student:dashboard'))
        self.assertNotContains(dashboard, 'Presentation venue updated')

    def test_published_announcement_can_be_edited_and_deleted(self):
        self.post_announcement()
        announcement = Announcement.objects.get()
        edit_url = reverse('dashboard_admin:announcement_edit', args=[announcement.pk])
        self.client.post(edit_url, {
            'title': 'Updated venue', 'category': 'Logistics',
            'audience': Announcement.Audience.STUDENTS,
            'priority': Announcement.Priority.URGENT,
            'body': 'Meet at **B12**.', 'submit_action': 'publish',
        })
        announcement.refresh_from_db()
        self.assertEqual(announcement.title, 'Updated venue')
        self.assertEqual(announcement.priority, Announcement.Priority.URGENT)
        delete_url = reverse('dashboard_admin:announcement_delete', args=[announcement.pk])
        self.assertEqual(self.client.post(delete_url).status_code, 302)
        self.assertFalse(Announcement.objects.exists())

    def test_non_organizer_cannot_access_announcement_management(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.announcements_url).status_code, 403)

    def test_student_dashboard_does_not_show_draft_announcement(self):
        Announcement.objects.create(
            hackathon=self.hackathon, title='Private draft', body='Not published', author='Organizer',
            is_draft=True,
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('student:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Private draft')

    def test_mentor_dashboard_hides_drafts_and_future_announcements(self):
        Announcement.objects.create(
            hackathon=self.hackathon, title='Mentor draft', body='Private', author='Organizer',
            audience=Announcement.Audience.MENTORS, is_draft=True,
        )
        Announcement.objects.create(
            hackathon=self.hackathon, title='Mentor scheduled', body='Not yet', author='Organizer',
            audience=Announcement.Audience.MENTORS, scheduled_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_login(self.mentor)
        response = self.client.get(reverse('mentor:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Mentor draft')
        self.assertNotContains(response, 'Mentor scheduled')

    def test_announcement_formatting_escapes_html_and_allows_safe_markdown(self):
        rendered = str(announcement_markdown('**Hello** <script>alert(1)</script>'))
        self.assertIn('<strong>Hello</strong>', rendered)
        self.assertNotIn('<script>', rendered)


class CopilotTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username='copilot-admin', password='test-pass', role='organization')
        self.student = User.objects.create_user(username='copilot-student', password='test-pass', role='student')
        now = timezone.now()
        self.hackathon = Hackathon.objects.create(
            name='Copilot Test Hackathon', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2), is_active=True,
        )
        self.team = Team.objects.create(
            hackathon=self.hackathon, name='Green Team', category='Climate',
            max_members=4, seeking_skill='Python',
        )
        HackathonRegistration.objects.create(hackathon=self.hackathon, user=self.student)
        self.url = reverse('dashboard_admin:copilot_ask')

    def test_snapshot_counts_are_calculated_from_database(self):
        facts, active_hackathon = build_hackathon_snapshot()

        self.assertEqual(active_hackathon, self.hackathon)
        self.assertEqual(facts['participants_inscrits'], 1)
        self.assertEqual(facts['equipes'], 1)
        self.assertEqual(facts['etudiants_affectes'], 0)
        self.assertEqual(facts['etudiants_sans_equipe'], 1)
        self.assertEqual(facts['categories_equipes'], [{'name': 'Climate', 'count': 1}])

    @patch('dashboard_admin.views.ask_copilot')
    def test_ajax_endpoint_returns_reply_and_keeps_chat_history(self, ask_mock):
        ask_mock.return_value = {
            'answer': 'Green Team needs a skills review.',
            'announcement_title': 'Deadline reminder',
            'announcement_body': 'Submit your project by Friday.',
        }
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url, {'question': 'Which team needs help?'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['answer'], ask_mock.return_value['answer'])
        self.assertEqual(self.client.session['admin_copilot_history'], [
            {'role': 'user', 'content': 'Which team needs help?'},
            {'role': 'assistant', 'content': 'Green Team needs a skills review.',
             'announcement_title': 'Deadline reminder',
             'announcement_body': 'Submit your project by Friday.'},
        ])
        ask_mock.assert_called_once()

    @patch('dashboard_admin.views.ask_copilot', side_effect=CopilotError('Ollama unavailable.'))
    def test_ollama_error_is_returned_as_json_and_saved_in_history(self, ask_mock):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url, {'question': 'Summarize the hackathon.'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'Ollama unavailable.')
        self.assertEqual(self.client.session['admin_copilot_history'][-1]['content'], 'Ollama unavailable.')

    def test_non_organizer_cannot_use_copilot_endpoint(self):
        self.client.force_login(self.student)

        response = self.client.post(self.url, {'question': 'Summarize the hackathon.'})

        self.assertEqual(response.status_code, 403)

    @patch('dashboard_admin.copilot.urllib.request.urlopen')
    def test_ollama_request_contains_database_facts_and_parses_structured_reply(self, urlopen_mock):
        expected = {
            'answer': 'One participant remains unassigned.',
            'announcement_title': '',
            'announcement_body': '',
        }
        urlopen_mock.return_value.__enter__.return_value.read.return_value = json.dumps({
            'message': {'content': json.dumps(expected)},
        }).encode('utf-8')
        facts = {'participants_inscrits': 7, 'equipes': 2}

        result = ask_copilot('Summarize the event.', facts)

        self.assertEqual(result, expected)
        request = urlopen_mock.call_args.args[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['messages'][1]['content'], json.dumps({
            'question': 'Summarize the event.', 'faits_database': facts,
        }, ensure_ascii=False))
        self.assertEqual(payload['stream'], False)
