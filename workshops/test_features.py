"""Tests de non-régression des fonctionnalités ateliers (replay, quiz, IA)."""

import json
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from student.models import Notification

from .models import BadgeAward, Booking, Certificate, Workshop, WorkshopQuiz
from .services.recommend import recommend
from .services.reminders import (
    send_feedback_reminders, send_starting_soon_reminders,
)
from .tests import _form_datetime, _make_user, _make_workshop

PASSWORD = 'Test1234!'


class WorkshopFeatureBase(TestCase):
    def setUp(self):
        self.admin = _make_user('feature_admin', role='admin')
        self.student = _make_user(
            'feature_student', role='student',
            skills=['Python', 'Django'], specialty='Backend')
        self.client = Client()
        self.now = timezone.now()

    def _recorded(self, **kwargs):
        defaults = dict(
            mode='recorded',
            title='Atelier Replay',
            starts_offset_h=-24,
            duration_h=2,
            capacity=0,
            video_file='workshop_videos/demo.mp4',
            available_until=self.now + timedelta(days=7),
        )
        defaults.update(kwargs)
        return _make_workshop(self.admin, **defaults)

    def _book(self, workshop):
        return Booking.objects.create(
            workshop=workshop, user=self.student,
            status=Booking.Status.CONFIRMED,
        )

    def _login_student(self):
        self.client.login(username=self.student.username, password=PASSWORD)


class ReplayMediaTests(WorkshopFeatureBase):
    def test_uploaded_video_is_rendered_in_detail_page(self):
        ws = self._recorded(title='Replay upload')
        self._book(ws)
        self._login_student()

        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<video')
        self.assertContains(response, ws.video_file.url)
        self.assertEqual(response.context['replay_video_source'], ws.video_file.url)
        self.assertEqual(response.context['replay_embed_url'], '')

    def test_youtube_and_vimeo_replays_are_embedded(self):
        cases = [
            (
                'youtube',
                'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'https://www.youtube.com/embed/dQw4w9WgXcQ',
            ),
            (
                'vimeo',
                'https://vimeo.com/76979871',
                'https://player.vimeo.com/video/76979871',
            ),
        ]
        for label, url, embed in cases:
            with self.subTest(provider=label):
                ws = self._recorded(
                    title=f'Replay {label}', video_file=None, replay_url=url)
                self._book(ws)
                self._login_student()

                response = self.client.get(
                    reverse('workshops:detail', kwargs={'slug': ws.slug}))

                self.assertContains(response, '<iframe')
                self.assertContains(response, embed)
                self.assertEqual(response.context['replay_video_source'], '')
                self.assertEqual(response.context['replay_embed_url'], embed)

    def test_direct_video_url_uses_html5_player(self):
        ws = self._recorded(
            title='Replay MP4', video_file=None,
            replay_url='https://cdn.example.com/cours.mp4')
        self._book(ws)
        self._login_student()

        response = self.client.get(
            reverse('workshops:detail', kwargs={'slug': ws.slug}))

        self.assertContains(response, '<video')
        self.assertContains(response, 'https://cdn.example.com/cours.mp4')

    def test_upload_takes_priority_over_replay_url(self):
        ws = self._recorded(
            title='Replay upload prioritaire',
            replay_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        self.assertEqual(ws.replay_video_source, ws.video_file.url)
        self.assertTrue(ws.replay_is_embed is False)


class ReplayVideoFormTests(TestCase):
    def setUp(self):
        self.admin = _make_user('upload_admin', role='admin')
        self.media_dir = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        self.client = Client()
        self.client.login(username=self.admin.username, password=PASSWORD)

    def test_admin_can_create_recorded_workshop_with_video_upload(self):
        video = SimpleUploadedFile(
            'replay.mp4', b'\x00\x00\x00\x18ftypmp42',
            content_type='video/mp4')

        response = self.client.post(reverse('workshops:create'), {
            'title': 'Atelier vidéo',
            'description': 'Replay uploadé',
            'speaker_name': 'Alice',
            'topic_tags_raw': 'Python, Vidéo',
            'mode': 'recorded',
            'level': 'beginner',
            'video_file': video,
            'starts_at': _form_datetime(days=3, hour=10),
            'ends_at': _form_datetime(days=3, hour=12),
            'capacity': 0,
            'is_open': 'on',
        })

        ws = Workshop.objects.get(title='Atelier vidéo')
        self.assertRedirects(response, ws.get_absolute_url())
        self.assertTrue(ws.video_file.name.endswith('replay.mp4'))
        detail = self.client.get(ws.get_absolute_url())
        self.assertContains(detail, '/media/workshop_videos/replay.mp4')
        self.assertContains(detail, '<video')


class ReplayQuizJourneyTests(WorkshopFeatureBase):
    def _make_quiz(self, ws):
        first = WorkshopQuiz.objects.create(
            workshop=ws, question='Quelle est la capitale de la France ?',
            option_a='Paris', option_b='Lyon', option_c='Nice', option_d='Lille',
            correct_index=0, explanation='Paris est la capitale.',
            created_by=self.admin,
        )
        second = WorkshopQuiz.objects.create(
            workshop=ws, question='Quel framework Python est utilisé ?',
            option_a='Laravel', option_b='Django', option_c='Rails', option_d='Spring',
            correct_index=1, explanation='Django est un framework Python.',
            created_by=self.admin,
        )
        return first, second

    def test_replay_requires_quiz_then_issues_certificate_and_badge(self):
        ws = self._recorded(title='Replay avec quiz')
        first, second = self._make_quiz(ws)
        booking = self._book(ws)
        self._login_student()

        response = self.client.post(
            reverse('workshops:replay_complete', args=[ws.pk]))

        self.assertRedirects(
            response, reverse('workshops:quiz', args=[ws.pk]),
            fetch_redirect_response=False)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.replay_progress, 100)
        self.assertFalse(Certificate.objects.filter(
            workshop=ws, user=self.student).exists())

        failed = self.client.post(
            reverse('workshops:quiz_submit', args=[ws.pk]),
            {f'question_{first.pk}': '1', f'question_{second.pk}': '3'},
        )
        self.assertEqual(failed.status_code, 200)
        self.assertFalse(failed.context['passed'])
        self.assertFalse(Certificate.objects.filter(
            workshop=ws, user=self.student).exists())

        passed = self.client.post(
            reverse('workshops:quiz_submit', args=[ws.pk]),
            {f'question_{first.pk}': '0', f'question_{second.pk}': '1'},
        )
        self.assertEqual(passed.status_code, 200)
        self.assertTrue(passed.context['passed'])
        self.assertEqual(passed.context['percentage'], 100)
        self.assertIsNotNone(passed.context['certificate'])
        self.assertIsNotNone(passed.context['badge_award'])

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.ATTENDED)
        self.assertTrue(Certificate.objects.filter(
            workshop=ws, user=self.student).exists())
        self.assertTrue(BadgeAward.objects.filter(
            user=self.student, workshop=ws, badge__slug='first-workshop').exists())

        feedback = self.client.get(
            reverse('workshops:rate', args=[ws.pk]))
        self.assertEqual(feedback.status_code, 200)


class RecommendationTests(TestCase):
    def setUp(self):
        self.admin = _make_user('reco_admin', role='admin')
        self.student = _make_user(
            'reco_student', role='student',
            skills=['Rust'], specialty='Systems')

    def test_past_workshops_are_never_recommended(self):
        past = _make_workshop(
            self.admin, title='Atelier passé', starts_offset_h=-3,
            duration_h=2)
        upcoming = _make_workshop(
            self.admin, title='Atelier futur', starts_offset_h=48,
            duration_h=2)
        for workshop in (past, upcoming):
            workshop.topic_tags = ['Rust']
            workshop.save(update_fields=['topic_tags'])

        with patch('workshops.services.recommend._ollama_ranking',
                   return_value=None):
            result = recommend(self.student, [past, upcoming])

        self.assertEqual([ws.pk for ws in result], [upcoming.pk])

    def test_expired_replay_is_not_recommended(self):
        expired = _make_workshop(
            self.admin, mode='recorded', title='Replay expiré',
            starts_offset_h=2, duration_h=2,
            replay_url='https://example.com/replay.mp4',
            available_until=timezone.now() - timedelta(hours=1),
        )
        available = _make_workshop(
            self.admin, mode='recorded', title='Replay disponible',
            starts_offset_h=2, duration_h=2,
            replay_url='https://example.com/replay.mp4',
            available_until=timezone.now() + timedelta(days=5),
        )

        with patch('workshops.services.recommend._ollama_ranking',
                   return_value=None):
            result = recommend(self.student, [expired, available])

        self.assertEqual([ws.pk for ws in result], [available.pk])

    def test_ollama_cannot_promote_an_unrelated_workshop(self):
        unrelated = _make_workshop(
            self.admin, title='Figma UX', mode='online',
            starts_offset_h=2, duration_h=2)
        unrelated.description = 'Design with Figma'
        unrelated.topic_tags = ['Figma', 'Design']
        unrelated.save(update_fields=['description', 'topic_tags'])

        with patch(
            'workshops.services.recommend._ollama_ranking',
            return_value=[{'id': unrelated.pk, 'score': 100, 'reason': 'IA'}],
        ):
            result = recommend(self.student, [unrelated])

        self.assertEqual(result[0].ai_score, 0)


class WorkshopReminderTests(WorkshopFeatureBase):
    def test_starting_soon_is_notified_once(self):
        ws = _make_workshop(
            self.admin, mode='online', title='Live imminent',
            starts_offset_h=2, duration_h=1)
        booking = self._book(ws)

        self.assertEqual(send_starting_soon_reminders(user=self.student), 1)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.reminder_sent_at)
        notification = Notification.objects.get(
            user=self.student, title='Votre atelier commence bientôt')
        self.assertIn(ws.title, notification.message)

        self.assertEqual(send_starting_soon_reminders(user=self.student), 0)
        self.assertEqual(Notification.objects.filter(
            user=self.student,
            title='Votre atelier commence bientôt').count(), 1)

    def test_finished_workshop_sends_feedback_reminder_once(self):
        ws = _make_workshop(
            self.admin, title='Atelier terminé',
            starts_offset_h=-4, duration_h=2)
        booking = self._book(ws)

        self.assertEqual(send_feedback_reminders(user=self.student), 1)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.feedback_reminder_sent_at)
        self.assertTrue(Notification.objects.filter(
            user=self.student, title='Votre avis compte').exists())

        self.assertEqual(send_feedback_reminders(user=self.student), 0)
        self.assertEqual(Notification.objects.filter(
            user=self.student, title='Votre avis compte').count(), 1)

    def test_unfinished_replay_is_not_asked_for_feedback(self):
        ws = self._recorded(title='Replay non terminé')
        booking = self._book(ws)

        self.assertEqual(send_feedback_reminders(user=self.student), 0)
        booking.refresh_from_db()
        self.assertIsNone(booking.feedback_reminder_sent_at)


class WorkshopFeedbackTests(WorkshopFeatureBase):
    def test_student_can_review_a_finished_workshop(self):
        ws = _make_workshop(
            self.admin, title='Atelier terminé',
            starts_offset_h=-4, duration_h=2)
        booking = self._book(ws)
        self._login_student()

        response = self.client.post(
            reverse('workshops:rate', args=[ws.pk]),
            {'rating': 5, 'comment': 'Excellent atelier'},
        )

        self.assertRedirects(
            response, reverse('workshops:my_bookings'),
            fetch_redirect_response=False)
        booking.refresh_from_db()
        self.assertEqual(booking.rating, 5)
        self.assertEqual(booking.comment, 'Excellent atelier')

    def test_student_cannot_review_before_the_end(self):
        ws = _make_workshop(
            self.admin, title='Atelier futur',
            starts_offset_h=5, duration_h=2)
        booking = self._book(ws)
        self._login_student()

        response = self.client.post(
            reverse('workshops:rate', args=[ws.pk]), {'rating': 4})

        self.assertRedirects(
            response, reverse('workshops:detail', kwargs={'slug': ws.slug}),
            fetch_redirect_response=False)
        booking.refresh_from_db()
        self.assertIsNone(booking.rating)

    def test_unfinished_replay_cannot_be_reviewed(self):
        ws = self._recorded(title='Replay non terminé')
        booking = self._book(ws)
        self._login_student()

        response = self.client.post(
            reverse('workshops:rate', args=[ws.pk]), {'rating': 4})

        self.assertRedirects(
            response, reverse('workshops:detail', kwargs={'slug': ws.slug}),
            fetch_redirect_response=False)
        booking.refresh_from_db()
        self.assertIsNone(booking.rating)


class QuizOrganizerApiTests(WorkshopFeatureBase):
    def setUp(self):
        super().setUp()
        self.ws = self._recorded(title='Replay API')
        self.other_mentor = _make_user('feature_mentor', role='mentor')
        self.client.login(username=self.admin.username, password=PASSWORD)

    def _post_json(self, url, payload):
        return self.client.post(
            url, data=json.dumps(payload), content_type='application/json')

    def test_owner_can_save_generated_questions(self):
        payload = {'questions': [
            {
                'question': 'Question générée ?',
                'options': ['A', 'B', 'C', 'D'],
                'correct_index': 1,
                'explanation': 'Parce que B.',
            },
            {'question': 'Question incomplète ?', 'options': ['A']},
        ]}

        response = self._post_json(
            reverse('workshops:api_save_quiz_questions', args=[self.ws.pk]),
            payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped'], 1)
        question = WorkshopQuiz.objects.get(workshop=self.ws)
        self.assertEqual(question.correct_option(), 'B')

    def test_student_cannot_save_questions(self):
        self.client.logout()
        self._login_student()

        response = self._post_json(
            reverse('workshops:api_save_quiz_questions', args=[self.ws.pk]),
            {'questions': [{
                'question': 'Pirate ?',
                'options': ['A', 'B', 'C', 'D'],
                'correct_index': 0,
            }]})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(WorkshopQuiz.objects.filter(workshop=self.ws).exists())

    def test_non_owner_mentor_cannot_suggest_options(self):
        self.client.logout()
        self.client.login(
            username=self.other_mentor.username, password=PASSWORD)

        response = self._post_json(
            reverse('workshops:api_suggest_quiz_options', args=[self.ws.pk]),
            {'question': 'Quelle bonne réponse ?'})

        self.assertEqual(response.status_code, 403)

    def test_suggest_options_returns_ollama_payload(self):
        suggestion = {
            'options': ['Paris', 'Lyon', 'Nice', 'Lille'],
            'correct_index': 0,
            'explanation': 'Paris est la capitale.',
        }
        with patch(
            'workshops.services.ollama_ai.is_ollama_available',
            return_value=True,
        ), patch(
            'workshops.services.ollama_ai.suggest_quiz_options',
            return_value=suggestion,
        ):
            response = self._post_json(
                reverse(
                    'workshops:api_suggest_quiz_options', args=[self.ws.pk]),
                {'question': 'Quelle est la capitale de la France ?'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['options'], suggestion['options'])
        self.assertEqual(data['correct_index'], 0)


class WorkshopCountdownTests(TestCase):
    def test_my_bookings_shows_countdown_for_upcoming_workshop(self):
        admin = _make_user('countdown_admin', role='admin')
        student = _make_user('countdown_student', role='student')
        ws = _make_workshop(
            admin, mode='online', title='Live à venir',
            starts_offset_h=3, duration_h=1)
        Booking.objects.create(
            workshop=ws, user=student, status=Booking.Status.CONFIRMED)

        self.client.login(username=student.username, password=PASSWORD)
        response = self.client.get(reverse('workshops:my_bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-workshop-countdown')
        self.assertContains(response, ws.title)
        self.assertTrue(any(
            booking.is_upcoming for booking in response.context['bookings']))
