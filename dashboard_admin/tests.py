from datetime import timedelta
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard_admin.copilot import CopilotError, ask_copilot, build_hackathon_snapshot
from student.models import Announcement, Hackathon, HackathonRegistration, Milestone, Team, TeamMembership
from dashboard_admin.team_formation import generate_team_plan
from dashboard_admin.announcement_generator import (
    AUDIENCE_TEAMS_WITHOUT_SUBMISSION, AnnouncementGenerationError,
    generate_announcement_draft,
)
from dashboard_admin.project_evaluation import (
    JUDGING_RUBRIC, ProjectEvaluationError, analyze_project_submission, build_project_evidence,
)
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


class TeamFormationCoverageTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        now = timezone.now()
        self.event = Hackathon.objects.create(
            name='Formation Coverage Hackathon', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2), is_active=True,
        )

    def student(self, username, **fields):
        return self.User.objects.create_user(username=username, role='student', **fields)

    def test_team_plan_balances_skills_roles_preferences_and_availability(self):
        team = Team.objects.create(
            hackathon=self.event, name='Climate Team', category='Climate action',
            project_name='Green city', description='Climate data', project_pitch='Reduce emissions',
            max_members=3, seeking_skill='Python, UX; business',
        )
        existing = self.student(
            'formation-existing', skills=['Python'], specialty='backend developer',
            availability_windows=['weekday_evening'],
        )
        TeamMembership.objects.create(team=team, user=existing)
        designer = self.student(
            'formation-designer', first_name='Alex', last_name='Design', skills=['Figma', 'UX'],
            preferred_roles=['designer'], preferred_categories='climate, accessibility',
            availability_windows=['weekday_evening', 'weekend'],
        )
        business = self.student(
            'formation-business', skills=['Marketing'], specialty='sales',
            preferred_roles=['business'], availability_windows=['flexible', 'invalid'],
        )
        outsider = self.student('formation-outsider', is_active=False, skills=['Rust'])
        for person in (designer, business, outsider):
            HackathonRegistration.objects.create(hackathon=self.event, user=person)

        plan = generate_team_plan()

        self.assertEqual(plan['hackathon_id'], self.event.pk)
        self.assertEqual(plan['unassigned_count'], 2)
        self.assertEqual(plan['remaining_count'], 0)
        self.assertEqual(len(plan['assignments']), 2)
        recommendation = plan['recommendations'][0]
        self.assertEqual(recommendation['current_count'], 1)
        self.assertEqual(recommendation['recommended_count'], 3)
        self.assertTrue(recommendation['full'])
        self.assertEqual(recommendation['missing_skills'], ['UX', 'business'])
        self.assertTrue(any('Projet proche' in reason for item in recommendation['additions'] for reason in item['reasons']))

    def test_plan_without_open_teams_keeps_students_unassigned(self):
        student = self.student('formation-no-team', skills=[''], is_active=True)
        HackathonRegistration.objects.create(hackathon=self.event, user=student)
        full_team = Team.objects.create(hackathon=self.event, name='Full', max_members=1)
        member = self.student('formation-full-member')
        TeamMembership.objects.create(team=full_team, user=member)

        plan = generate_team_plan()

        self.assertEqual(plan['assignments'], [])
        self.assertEqual(plan['remaining_count'], 1)
        self.assertEqual(plan['remaining_students'][0]['name'], student.username)
        self.assertEqual(plan['recommendations'][0]['missing_roles'], [])


class OrganizerViewsCoverageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username='view-admin', role='organization')
        self.student = User.objects.create_user(
            username='view-participant', email='participant@example.test', role='student',
            first_name='Pat', last_name='Student', school='Example', skills=['Python'],
        )
        self.mentor = User.objects.create_user(username='view-mentor', role='mentor')
        now = timezone.now()
        self.event = Hackathon.objects.create(
            name='Organizer Views Event', starts_at=now - timedelta(hours=2),
            ends_at=now + timedelta(days=2), is_active=True,
        )
        self.team = Team.objects.create(
            hackathon=self.event, name='View Team', category='AI', max_members=3,
        )
        HackathonRegistration.objects.create(hackathon=self.event, user=self.student)
        TeamMembership.objects.create(team=self.team, user=self.student)
        self.client.force_login(self.admin)

    def test_dashboard_participants_teams_events_and_judging_pages_render(self):
        pages = (
            reverse('dashboard_admin:dashboard'),
            reverse('dashboard_admin:participants'),
            reverse('dashboard_admin:participants') + '?role=student&status=assigned&q=pat',
            reverse('dashboard_admin:teams'),
            reverse('dashboard_admin:teams') + f'?hackathon={self.event.pk}',
            reverse('dashboard_admin:events_overview'),
            reverse('dashboard_admin:judging'),
        )
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_participant_export_detail_team_changes_and_activation(self):
        export = self.client.get(reverse('dashboard_admin:participants_export') + '?role=student')
        self.assertEqual(export.status_code, 200)
        self.assertIn('participant@example.test', export.content.decode('utf-8-sig'))
        detail = self.client.get(reverse('dashboard_admin:participant_detail', args=[self.student.pk]))
        self.assertEqual(detail.status_code, 200)

        second_team = Team.objects.create(hackathon=self.event, name='Second team', max_members=2)
        assign = self.client.post(reverse('dashboard_admin:participant_set_team', args=[self.student.pk]),
                                  {'team_id': second_team.pk})
        self.assertRedirects(assign, reverse('dashboard_admin:participants'))
        self.assertTrue(TeamMembership.objects.filter(user=self.student, team=second_team).exists())
        remove = self.client.post(reverse('dashboard_admin:participant_set_team', args=[self.student.pk]), {'team_id': ''})
        self.assertRedirects(remove, reverse('dashboard_admin:participants'))
        self.assertFalse(TeamMembership.objects.filter(user=self.student).exists())

        toggle_url = reverse('dashboard_admin:participant_toggle_active', args=[self.mentor.pk])
        self.client.post(toggle_url)
        self.mentor.refresh_from_db()
        self.assertFalse(self.mentor.is_active)
        self.client.post(toggle_url)
        self.mentor.refresh_from_db()
        self.assertTrue(self.mentor.is_active)

    def test_team_assignment_rejects_full_team_and_unsupported_method(self):
        self.team.max_members = 1
        self.team.save(update_fields=['max_members'])
        other = get_user_model().objects.create_user(username='another-student', role='student')
        response = self.client.post(reverse('dashboard_admin:participant_set_team', args=[other.pk]),
                                    {'team_id': self.team.pk})
        self.assertRedirects(response, reverse('dashboard_admin:participants'))
        self.assertFalse(TeamMembership.objects.filter(user=other).exists())
        self.assertEqual(self.client.get(reverse('dashboard_admin:participant_toggle_active', args=[other.pk])).status_code, 405)

    def test_dashboard_saves_drafts_and_handles_invalid_actions(self):
        url = reverse('dashboard_admin:dashboard')
        no_content = self.client.post(url, {'action': 'save_announcement', 'announcement_title': '  ', 'announcement_body': ''})
        self.assertRedirects(no_content, url)
        self.assertFalse(Announcement.objects.exists())
        saved = self.client.post(url, {
            'action': 'save_announcement', 'announcement_title': 'Draft from dashboard',
            'announcement_body': 'Review projects before Friday.',
        })
        self.assertRedirects(saved, url)
        self.assertTrue(Announcement.objects.get().is_draft)

    def test_dashboard_rejects_draft_without_active_event(self):
        self.event.is_active = False
        self.event.save(update_fields=['is_active'])
        response = self.client.post(reverse('dashboard_admin:dashboard'), {
            'action': 'save_announcement', 'announcement_title': 'No event',
            'announcement_body': 'A draft cannot be attached.',
        })
        self.assertRedirects(response, reverse('dashboard_admin:dashboard'))
        self.assertFalse(Announcement.objects.exists())

    def test_team_formation_generate_apply_and_stale_plan(self):
        candidate = get_user_model().objects.create_user(
            username='formation-route-candidate', role='student', skills=['Python'],
        )
        HackathonRegistration.objects.create(hackathon=self.event, user=candidate)
        url = reverse('dashboard_admin:team_formation')
        generated = self.client.post(url, {'action': 'generate'})
        self.assertRedirects(generated, url)
        self.assertTrue(self.client.session['team_formation_plan']['assignments'])
        applied = self.client.post(url, {'action': 'apply'})
        self.assertRedirects(applied, reverse('dashboard_admin:participants'))
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=candidate).exists())
        self.assertNotIn('team_formation_plan', self.client.session)

        candidate2 = get_user_model().objects.create_user(username='formation-stale-candidate', role='student')
        HackathonRegistration.objects.create(hackathon=self.event, user=candidate2)
        self.client.post(url, {'action': 'generate'})
        candidate2.is_active = False
        candidate2.save(update_fields=['is_active'])
        stale = self.client.post(url, {'action': 'apply'})
        self.assertRedirects(stale, url)
        self.assertNotIn('team_formation_plan', self.client.session)

    def test_team_formation_apply_without_plan_redirects(self):
        url = reverse('dashboard_admin:team_formation')
        response = self.client.post(url, {'action': 'apply'})
        self.assertRedirects(response, url)

    def test_events_create_edit_and_invalid_dates(self):
        url = reverse('dashboard_admin:events_overview')
        invalid = self.client.post(url, {
            'name': 'Invalid event', 'starts_at': '2026-11-01T12:00',
            'ends_at': '2026-11-01T11:00', 'location': 'Online', 'is_active': 'on',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(Hackathon.objects.filter(name='Invalid event').exists())

        edit_url = reverse('dashboard_admin:event_edit', args=[self.event.pk])
        response = self.client.post(edit_url, {
            'name': 'Renamed coverage event', 'edition': '2026',
            'starts_at': '2026-10-23T10:00', 'ends_at': '2026-10-27T10:00',
            'location': 'Tunis', 'is_active': 'on',
        })
        self.assertRedirects(response, url)
        self.event.refresh_from_db()
        self.assertEqual(self.event.name, 'Renamed coverage event')

    @patch('dashboard_admin.views.generate_announcement_draft', side_effect=[
        ValueError('Invalid topic.'),
        {'title': 'Generated draft', 'body': 'Editable text', 'audience': 'all'},
    ])
    def test_announcement_generator_endpoint_returns_validation_and_result(self, generate_mock):
        url = reverse('dashboard_admin:announcement_generate')
        invalid = self.client.post(url, {'topic': ''})
        self.assertEqual(invalid.status_code, 400)
        response = self.client.post(url, {'topic': 'Reminder', 'audience': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], 'Generated draft')
        self.assertEqual(generate_mock.call_count, 2)

    def test_plan_without_active_hackathon_uses_existing_teams_and_all_students(self):
        self.event.is_active = False
        self.event.save(update_fields=['is_active'])
        team = Team.objects.create(hackathon=self.event, name='Fallback team', max_members=2)
        student = get_user_model().objects.create_user(
            username='formation-fallback', role='student', skills=['TypeScript', 'PostgreSQL'],
            preferred_roles=['developer', 'product'], preferred_categories='empty preference',
            availability_windows=['weekday_day'],
        )

        plan = generate_team_plan()

        self.assertIsNone(plan['hackathon_id'])
        self.assertTrue(plan['hackathon_name'].startswith('Toutes les'))
        self.assertEqual(plan['assignments'][0]['team_id'], team.pk)
        self.assertEqual(plan['recommendations'][0]['missing_roles'], [])


class AnnouncementAndJuryServiceCoverageTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.event = Hackathon.objects.create(
            name='AI services event', starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2), is_active=True,
        )

    @patch('dashboard_admin.announcement_generator.urllib.request.urlopen')
    def test_announcement_generator_targets_missing_teams_and_returns_editable_draft(self, urlopen_mock):
        milestone = Milestone.objects.create(
            hackathon=self.event, title='Final delivery', due_at=timezone.now() + timedelta(days=1),
        )
        first = Team.objects.create(hackathon=self.event, name='Team A')
        Team.objects.create(hackathon=self.event, name='Team B')
        from student.models import Submission
        Submission.objects.create(
            team=first, milestone=milestone, status=Submission.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        draft = {'title': 'Submission reminder', 'body': 'Bonjour {{team_name}}'}
        urlopen_mock.return_value.__enter__.return_value.read.return_value = json.dumps({
            'message': {'content': json.dumps(draft)},
        }).encode('utf-8')

        result = generate_announcement_draft(
            audience=AUDIENCE_TEAMS_WITHOUT_SUBMISSION, topic='Reminder',
            tone='direct', message_type='email',
        )

        self.assertEqual(result['title'], draft['title'])
        self.assertEqual(result['target_team_count'], 1)
        self.assertEqual(result['target_teams'], ['Team B'])
        self.assertTrue(result['is_targeted_email'])
        self.assertEqual(result['milestone'], 'Final delivery')
        request = urlopen_mock.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/api/chat'))

    def test_announcement_generator_validates_inputs_and_target_setup(self):
        for kwargs in (
            {'audience': 'all', 'topic': ' ', 'tone': 'direct', 'message_type': 'annonce'},
            {'audience': 'all', 'topic': 'Reminder', 'tone': 'unknown', 'message_type': 'annonce'},
            {'audience': 'all', 'topic': 'Reminder', 'tone': 'direct', 'message_type': 'sms'},
            {'audience': 'unknown', 'topic': 'Reminder', 'tone': 'direct', 'message_type': 'annonce'},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_announcement_draft(**kwargs)

        with self.assertRaises(ValueError):
            generate_announcement_draft(
                audience=AUDIENCE_TEAMS_WITHOUT_SUBMISSION, topic='Reminder',
                tone='direct', message_type='annonce',
            )

    def submission_stub(self, **overrides):
        team = SimpleNamespace(name='Evidence Team', hackathon=self.event, project_name='Team Project',
                               category='Climate', project_pitch='Reduce waste')
        milestone = SimpleNamespace(title='Prototype', description='Build a demo')
        fields = {
            'file': None, 'team': team, 'milestone': milestone, 'project_name': 'Project name',
            'category': '', 'description': 'A grounded description', 'github_url': '',
            'demo_url': '', 'video_url': '', 'get_status_display': lambda: 'Submitted',
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    @patch('dashboard_admin.project_evaluation.urllib.request.urlopen')
    def test_project_evaluation_builds_evidence_and_filters_model_output(self, urlopen_mock):
        response = {
            'summary': 'Evidence summary', 'objectives': ['Goal', '', 'x' * 600],
            'technologies': ['Python'], 'use_cases': [], 'deliverables': ['README'],
            'rubric_review': [
                {'criterion': JUDGING_RUBRIC[0]['label'], 'evidence': 'Observed', 'jury_should_verify': 'Demo'},
                {'criterion': 'Invalid criterion', 'evidence': 'Ignore', 'jury_should_verify': 'Ignore'},
            ],
            'jury_questions': ['What did you test?'], 'missing_evidence': ['User feedback'],
        }
        urlopen_mock.return_value.__enter__.return_value.read.return_value = json.dumps({
            'message': {'content': json.dumps(response)},
        }).encode('utf-8')
        submission = self.submission_stub()

        evidence = build_project_evidence(submission)
        result = analyze_project_submission(submission)

        self.assertEqual(evidence['note_archive'], 'Aucun fichier ZIP joint.')
        self.assertEqual(evidence['equipe'], 'Evidence Team')
        self.assertEqual(result['project'], 'Project name')
        self.assertEqual(len(result['objectives'][1]), 500)
        self.assertEqual(len(result['rubric_review']), 1)
        self.assertEqual(result['rubric_review'][0]['weight_percent'], 25)

    @patch('dashboard_admin.project_evaluation.urllib.request.urlopen', side_effect=urllib.error.URLError('offline'))
    def test_project_evaluation_reports_unreachable_backend(self, _urlopen_mock):
        with self.assertRaises(ProjectEvaluationError):
            analyze_project_submission(self.submission_stub())

    def test_dashboard_export_csv(self):
        admin = get_user_model().objects.create_user(username='export-admin', password='password123', role='organization')
        self.client.login(username='export-admin', password='password123')
        url = reverse('dashboard_admin:dashboard_export')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('hackflow-dashboard-', response['Content-Disposition'])
        content = response.content.decode('utf-8')
        self.assertIn('RAPPORT SYNTHÈSE HACKFLOW', content)
        self.assertIn('INDICATEURS CLÉS (KPIS)', content)
        self.assertIn('ÉQUIPES ET PROJETS', content)
        self.assertIn('PARTICIPANTS (ÉTUDIANTS & MENTORS)', content)
