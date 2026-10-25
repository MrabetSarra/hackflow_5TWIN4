import json
import os
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from . import ai_services, ai_views, gemini
from .models import AIJob, Challenge, Track
from .tests import make_hackathon

REAL_ENQUEUE = ai_views.enqueue_job
KEY = 'test-secret-key-123'

DRAFT_OK = json.dumps({
    'alternative_titles': ['Titre A', 'Titre B'], 'short_description': 'Une courte description.',
    'description': 'Une description complète du hackathon.', 'rules': 'Règle 1\nRègle 2',
    'challenge_ideas': [{'title': 'Idée 1', 'difficulty': 'beginner', 'why': 'Parce que.'}],
})
CHALLENGE_OK = json.dumps({
    'alternative_titles': ['Défi A'], 'short_description': 'Court.', 'description': 'Détaillée.',
    'objectives': 'Obj 1\nObj 2', 'problem_statement': 'Problème.', 'constraints': 'C1', 'deliverables': 'L1',
    'guidelines': 'G1', 'technologies': ['Python', 'Django'], 'difficulty': 'advanced', 'reward_ideas': ['Trophée'],
})
COACH_OK = json.dumps({
    'summary': 'Résumé simple.', 'explanation': 'Explication claire.', 'why_for_you': 'Bon profil.',
    'difficulty_feel': 'Moyen.', 'first_steps': ['Lire'], 'tips': ['Tester'], 'pitfalls': ['Trop large'],
    'skills_to_learn': ['Docker'], 'bonus_ideas': ['Démo'],
})
MENTOR_OK = json.dumps({
    'summary': 'En bref.', 'key_points': ['A'], 'team_difficulties': ['B'], 'questions_to_ask': ['C?'],
    'mentoring_tips': ['D'], 'resources': ['E'],
})


def sync_enqueue(job):
    ai_services.run_job(job.pk)


class AIBase(TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {
            'GEMINI_API_KEY': KEY, 'GEMINI_MODEL': 'model-main', 'GEMINI_FALLBACK_MODEL': 'model-backup',
            'HACKATHONS_AI_REQUESTS_PER_HOUR': '50',
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        enqueue = mock.patch('hackathons.ai_views.enqueue_job', side_effect=sync_enqueue)
        enqueue.start()
        self.addCleanup(enqueue.stop)

        self.org = User.objects.create_user('aorg', password='x', role='organization')
        self.student = User.objects.create_user(
            'astu', password='x', role='student', skills=['Python / Django', 'PostgreSQL'], specialty='Backend')
        self.mentor = User.objects.create_user('amen', password='x', role='mentor')
        self.track = Track.objects.create(name='GreenTech')
        self.h = make_hackathon(self.track, name='Eco Jam', short_description='Hackathon écologie')
        self.py = Challenge.objects.create(
            hackathon=self.h, title='API de suivi carbone', status='published', technologies='Python, Django, PostgreSQL',
            description='Construire une API REST pour mesurer les émissions.')
        self.ui = Challenge.objects.create(
            hackathon=self.h, title='Maquettes Figma', status='published', technologies='Figma, UX',
            description='Concevoir une interface et un prototype.')

    def start(self, feature, data=None, user=None):
        self.client.force_login(user or self.org)
        return self.client.post(reverse('hackathons:ai_start', args=[feature]), data or {})


class GeminiClientTests(AIBase):
    def test_primary_model_success_without_fallback(self):
        with mock.patch('hackathons.gemini._call', return_value=DRAFT_OK) as call:
            data, meta = gemini.generate_json('prompt', lambda d: d)
        self.assertEqual(meta['model'], 'model-main')
        self.assertFalse(meta['fallback_used'])
        call.assert_called_once()

    def test_fallback_model_used_when_primary_fails(self):
        calls = []

        def fake(model, *args, **kwargs):
            calls.append(model)
            if model == 'model-main':
                raise gemini.GeminiError('Le quota Gemini est atteint.')
            return DRAFT_OK

        with mock.patch('hackathons.gemini._call', side_effect=fake):
            data, meta = gemini.generate_json('prompt', lambda d: d)
        self.assertEqual(calls, ['model-main', 'model-backup'])
        self.assertTrue(meta['fallback_used'])
        self.assertEqual(meta['model'], 'model-backup')
        self.assertIn('quota', meta['primary_error'])

    def test_invalid_json_from_primary_triggers_fallback(self):
        with mock.patch('hackathons.gemini._call', side_effect=['pas du json', DRAFT_OK]):
            _data, meta = gemini.generate_json('prompt', lambda d: d)
        self.assertTrue(meta['fallback_used'])

    def test_both_models_failing_raises_readable_error(self):
        with mock.patch('hackathons.gemini._call', side_effect=gemini.GeminiError('Gemini est momentanément indisponible.')):
            with self.assertRaises(gemini.GeminiError) as ctx:
                gemini.generate_json('prompt', lambda d: d)
        self.assertIn('secours', str(ctx.exception))
        self.assertTrue(ctx.exception.meta['fallback_used'])

    def test_missing_api_key_is_explicit_and_makes_no_call(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': ''}), mock.patch('hackathons.gemini._call') as call:
            with self.assertRaises(gemini.GeminiNotConfigured) as ctx:
                gemini.generate_json('prompt', lambda d: d)
        self.assertIn('GEMINI_API_KEY', str(ctx.exception))
        call.assert_not_called()


class AdminAssistantTests(AIBase):
    def test_hackathon_and_challenge_forms_show_ai_button(self):
        self.client.force_login(self.org)
        for url in (reverse('hackathons:hackathon_create'), reverse('hackathons:challenge_create', args=[self.h.pk])):
            body = self.client.get(url).content.decode()
            self.assertIn('Assistant IA', body)
            self.assertIn('hf-ai-modal', body)
        body = self.client.get(reverse('hackathons:child_create', args=[self.py.pk, 'schedule'])).content.decode()
        self.assertNotIn('hf-ai-modal', body)

    def test_hackathon_draft_returns_validated_proposals_and_logs_metrics(self):
        with mock.patch('hackathons.gemini._call', return_value=DRAFT_OK):
            response = self.start('hackathon_draft', {'title': 'Green Jam 2026', 'instructions': 'ton formel'})
        body = response.json()
        self.assertEqual(body['status'], 'done')
        self.assertEqual(body['result']['short_description'], 'Une courte description.')
        self.assertEqual(body['result']['challenge_ideas'][0]['difficulty'], 'beginner')
        job = AIJob.objects.get()
        self.assertEqual(job.model_used, 'model-main')
        self.assertGreaterEqual(job.latency_ms, 0)
        self.assertGreater(job.input_chars, 0)
        self.assertGreater(job.output_chars, 0)
        self.assertNotIn(KEY, response.content.decode())

    def test_challenge_draft_maps_all_fields(self):
        with mock.patch('hackathons.gemini._call', return_value=CHALLENGE_OK):
            body = self.start('challenge_draft', {'title': 'Smart grid', 'hackathon_id': self.h.pk}).json()
        self.assertEqual(body['result']['technologies'], ['Python', 'Django'])
        self.assertEqual(body['result']['difficulty'], 'advanced')
        self.assertIn('Obj 1', body['result']['objectives'])

    def test_title_required_and_roles_enforced(self):
        self.assertEqual(self.start('hackathon_draft', {'title': 'ab'}).status_code, 400)
        self.assertEqual(self.start('hackathon_draft', {'title': 'Un titre'}, user=self.student).status_code, 403)
        self.assertEqual(self.start('student_coach', {'challenge_id': self.py.pk}, user=self.org).status_code, 403)

    def test_identical_request_is_served_from_cache(self):
        with mock.patch('hackathons.gemini._call', return_value=DRAFT_OK) as call:
            first = self.start('hackathon_draft', {'title': 'Green Jam 2026'}).json()
            second = self.start('hackathon_draft', {'title': 'Green Jam 2026'}).json()
            refreshed = self.start('hackathon_draft', {'title': 'Green Jam 2026', 'refresh': '1'}).json()
        self.assertFalse(first['cached'])
        self.assertTrue(second['cached'])
        self.assertFalse(refreshed['cached'])
        self.assertEqual(call.call_count, 2)

    def test_failed_generation_returns_understandable_error(self):
        with mock.patch('hackathons.gemini._call', side_effect=gemini.GeminiError('Gemini est momentanément indisponible.')):
            body = self.start('hackathon_draft', {'title': 'Green Jam 2026'}).json()
        self.assertEqual(body['status'], 'failed')
        self.assertIn('secours', body['error'])
        self.assertEqual(AIJob.objects.get().status, AIJob.Status.FAILED)

    def test_missing_key_message_reaches_the_user(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            body = self.start('hackathon_draft', {'title': 'Green Jam 2026'}).json()
        self.assertEqual(body['status'], 'failed')
        self.assertIn('GEMINI_API_KEY', body['error'])

    def test_rate_limit(self):
        with mock.patch.dict(os.environ, {'HACKATHONS_AI_REQUESTS_PER_HOUR': '1'}), \
                mock.patch('hackathons.gemini._call', return_value=DRAFT_OK):
            self.assertEqual(self.start('hackathon_draft', {'title': 'Premier titre'}).status_code, 200)
            response = self.start('hackathon_draft', {'title': 'Second titre'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('limite', response.json()['error'])

    def test_queue_unavailable_marks_job_failed(self):
        job = AIJob.objects.create(user=self.org, feature='hackathon_draft', payload={'titre': 'x'}, payload_hash='z')
        with mock.patch('hackathons.tasks.run_ai_job.delay', side_effect=ConnectionError('broker down')):
            REAL_ENQUEUE(job)
        job.refresh_from_db()
        self.assertEqual(job.status, AIJob.Status.FAILED)
        self.assertIn('indisponible', job.error_message)


class StudentAITests(AIBase):
    def test_local_ranking_orders_by_student_skills(self):
        skills, ranked, hackathons = ai_services.rank_published(self.student)
        self.assertIn('Python / Django', skills)
        self.assertEqual(ranked[0]['challenge'], self.py)
        self.assertGreater(ranked[0]['score'], ranked[1]['score'])
        self.assertIn('Python / Django', ranked[0]['matched'])
        self.assertEqual(hackathons[0]['hackathon'], self.h)

    def test_draft_challenges_are_never_ranked(self):
        Challenge.objects.create(hackathon=self.h, title='Brouillon Python', status='draft', technologies='Python')
        _skills, ranked, _h = ai_services.rank_published(self.student)
        self.assertNotIn('Brouillon Python', [r['challenge'].title for r in ranked])

    def test_recommendation_page_renders_for_student_only(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('hackathons:ai_recommendations'))
        self.assertContains(response, 'API de suivi carbone')
        self.assertContains(response, 'Recommandations IA')
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse('hackathons:ai_recommendations')).status_code, 403)

    def test_recommend_filters_unknown_ids_and_keeps_order(self):
        answer = json.dumps({
            'advice': 'Commencez par l’API.',
            'challenges': [{'id': self.py.pk, 'reason': 'Python et SQL.', 'tip': 'Modélisez d’abord.'}, {'id': 99999, 'reason': 'x'}],
            'hackathons': [{'id': self.h.pk, 'reason': 'Bon thème.'}, {'id': 98765, 'reason': 'y'}],
        })
        with mock.patch('hackathons.gemini._call', return_value=answer):
            body = self.start('student_recommend', {}, user=self.student).json()
        self.assertEqual([c['id'] for c in body['result']['challenges']], [self.py.pk])
        self.assertEqual([h['id'] for h in body['result']['hackathons']], [self.h.pk])

    def test_recommend_requires_skills(self):
        no_skills = User.objects.create_user('noskill', password='x', role='student')
        body = self.start('student_recommend', {}, user=no_skills).json()
        self.assertEqual(body['status'], 'failed')
        self.assertIn('compétences', body['error'])

    def test_coach_returns_summary_and_tips_and_sends_profile(self):
        with mock.patch('hackathons.gemini._call', return_value=COACH_OK) as call:
            body = self.start('student_coach', {'challenge_id': self.py.pk}, user=self.student).json()
        self.assertEqual(body['result']['summary'], 'Résumé simple.')
        self.assertEqual(body['result']['tips'], ['Tester'])
        prompt = call.call_args[0][1]
        self.assertIn('Python / Django', prompt)
        self.assertNotIn('username', prompt)
        self.assertNotIn('email', prompt)

    def test_coach_rejects_unpublished_challenge(self):
        self.py.status = 'draft'
        self.py.save()
        self.client.force_login(self.student)
        response = self.client.post(reverse('hackathons:ai_start', args=['student_coach']), {'challenge_id': self.py.pk})
        self.assertEqual(response.status_code, 404)

    def test_job_status_and_feedback_are_private_to_owner(self):
        with mock.patch('hackathons.gemini._call', return_value=COACH_OK):
            body = self.start('student_coach', {'challenge_id': self.py.pk}, user=self.student).json()
        status_url = reverse('hackathons:ai_status', args=[body['job_id']])
        self.assertEqual(self.client.get(status_url).json()['status'], 'done')
        feedback_url = reverse('hackathons:ai_feedback', args=[body['job_id']])
        self.assertEqual(self.client.post(feedback_url, {'value': '1'}).status_code, 200)
        self.assertEqual(AIJob.objects.get(pk=body['job_id']).feedback, 1)
        self.assertEqual(self.client.post(feedback_url, {'value': '5'}).status_code, 400)
        self.client.force_login(self.org)
        self.assertEqual(self.client.get(status_url).status_code, 404)
        self.assertEqual(self.client.post(feedback_url, {'value': '1'}).status_code, 404)


class MentorAITests(AIBase):
    def test_mentor_page_and_explanations(self):
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(reverse('hackathons:ai_mentor')), 'Expliquer le défi')
        with mock.patch('hackathons.gemini._call', return_value=MENTOR_OK):
            challenge = self.start('mentor_explain', {'kind': 'challenge', 'id': self.py.pk}, user=self.mentor).json()
            hackathon = self.start('mentor_explain', {'kind': 'hackathon', 'id': self.h.pk}, user=self.mentor).json()
        self.assertEqual(challenge['result']['key_points'], ['A'])
        self.assertEqual(hackathon['status'], 'done')

    def test_mentor_ai_unavailable_for_students_and_invalid_target(self):
        self.assertEqual(self.start('mentor_explain', {'kind': 'challenge', 'id': self.py.pk}, user=self.student).status_code, 403)
        self.assertEqual(self.start('mentor_explain', {'kind': 'other', 'id': '1'}, user=self.mentor).status_code, 400)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('hackathons:ai_mentor')).status_code, 403)


class SidebarTests(AIBase):
    def test_sidebars_have_one_ai_link_each(self):
        expectations = (
            (self.student, 'hackathons:ai_recommendations', 'hackathons:ai_recommendations'),
            (self.mentor, 'hackathons:ai_mentor', 'hackathons:ai_mentor'),
        )
        for user, page_name, link_name in expectations:
            self.client.force_login(user)
            body = self.client.get(reverse(page_name)).content.decode()
            self.assertEqual(body.count(f'href="{reverse(link_name)}" class="nav-link-item'), 1, link_name)
