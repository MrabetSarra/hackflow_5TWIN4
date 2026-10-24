"""Tests du tri IA (Ollama simulé : aucun appel réseau, exécutables en CI)."""
import json
import tempfile
import urllib.error
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from student.models import MentorRequest

from . import ai, tasks
from .metrics import classification_report, confusion_matrix, latency_stats, percentile
from .models import RequestTriage
from .tests import MentorViewsTestBase

DEVOPS = 'DevOps, Docker & Cloud Deployment'
BACKEND = 'Back-End Development & Databases'
GOOD_RESPONSE = json.dumps({'category': DEVOPS, 'urgency': 'blocking', 'summary': 'Le conteneur ne démarre plus.'})


class MetricsTests(SimpleTestCase):
    def test_classification_report(self):
        y_true = ['a', 'a', 'b', 'b', 'c']
        y_pred = ['a', 'b', 'b', 'b', 'a']
        report = classification_report(y_true, y_pred, ['a', 'b', 'c'])
        self.assertEqual(report['accuracy'], 0.6)
        self.assertEqual(report['per_class']['a'], {'precision': 0.5, 'recall': 0.5, 'f1': 0.5, 'support': 2})
        self.assertEqual(report['per_class']['b']['precision'], 0.667)
        self.assertEqual(report['per_class']['c']['f1'], 0.0)
        self.assertEqual(report['confusion_matrix'], [[1, 1, 0], [0, 2, 0], [1, 0, 0]])

    def test_macro_ignores_classes_without_examples(self):
        report = classification_report(['a', 'b'], ['a', 'b'], ['a', 'b', 'c'])
        self.assertEqual(report['macro_f1'], 1.0)

    def test_confusion_matrix_ignores_unknown_labels(self):
        self.assertEqual(confusion_matrix(['a', 'x'], ['a', 'a'], ['a']), [[1]])

    def test_percentiles_and_latency(self):
        self.assertEqual(percentile([100, 200, 300, 400], 50), 250)
        self.assertIsNone(percentile([], 50))
        stats = latency_stats([1000, 1200, 1400])
        self.assertEqual((stats['mean_ms'], stats['p50_ms'], stats['max_ms']), (1200, 1200, 1400))
        self.assertEqual(latency_stats([])['count'], 0)


class AIServiceTests(TestCase):
    def test_categories_follow_student_form(self):
        self.assertIn(DEVOPS, ai.CATEGORIES)
        self.assertEqual(ai.URGENCIES, ['blocking', 'important', 'normal'])

    def test_parse_valid_response(self):
        self.assertEqual(ai.parse_response(GOOD_RESPONSE)['category'], DEVOPS)

    def test_parse_rejects_invalid_json_and_unknown_values(self):
        for raw in ('pas du json', '[]', json.dumps({'category': 'Cuisine', 'urgency': 'blocking'}),
                    json.dumps({'category': DEVOPS, 'urgency': 'panic'})):
            with self.subTest(raw=raw), self.assertRaises(ai.TriageError):
                ai.parse_response(raw)

    def test_secrets_are_redacted_before_sending(self):
        text = ai.build_ticket_text('Crash', 'password = SuperSecret123456 dans settings')
        self.assertNotIn('SuperSecret123456', text)

    def test_ollama_unreachable(self):
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('refused')):
            with self.assertRaisesRegex(ai.TriageError, 'pas joignable'):
                ai.call_ollama('ticket')

    def test_missing_model(self):
        error = urllib.error.HTTPError('http://x', 404, 'not found', {}, None)
        with mock.patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(ai.TriageError, 'ollama pull'):
                ai.call_ollama('ticket')

    def test_classify_returns_result_and_latency(self):
        with mock.patch.object(ai, 'call_ollama', return_value=GOOD_RESPONSE) as call:
            result, latency = ai.classify('Docker', 'Le conteneur crash')
        self.assertEqual(result['urgency'], 'blocking')
        self.assertGreaterEqual(latency, 0)
        self.assertIn('Docker', call.call_args.args[0])

    def test_suggest_mentor_by_specialty_and_load(self):
        User = get_user_model()
        busy = User.objects.create_user(username='busy', password='x-Strong-Pass-1', role='mentor',
                                        specialty='DevOps & Cloud')
        free = User.objects.create_user(username='free', password='x-Strong-Pass-1', role='mentor',
                                        specialty='Docker, Kubernetes')
        User.objects.create_user(username='maint', password='x-Strong-Pass-1', role='mentor',
                                 specialty='Maintenance applicative')
        student = User.objects.create_user(username='stu', password='x-Strong-Pass-1', role='student')
        MentorRequest.objects.create(student=student, mentor=busy, subject='x', category='x', description='x',
                                     status=MentorRequest.Status.ACCEPTED)
        self.assertEqual(ai.suggest_mentor(DEVOPS), free)
        # « ai » ne doit pas correspondre à « Maintenance » (mots entiers uniquement).
        self.assertIsNone(ai.suggest_mentor('AI, LLMs & Machine Learning'))


class TriageTaskTests(MentorViewsTestBase):
    def setUp(self):
        super().setUp()
        self.mentor.specialty = 'DevOps & Cloud'
        self.mentor.save()
        self.triage = RequestTriage.objects.create(help_request=self.pending)

    def test_run_triage_success(self):
        result = {'category': DEVOPS, 'urgency': 'blocking', 'summary': 'Crash Docker'}
        with mock.patch.object(tasks, 'classify', return_value=(result, 1234)):
            tasks.run_triage(self.triage.pk)
        self.triage.refresh_from_db()
        self.assertEqual(self.triage.status, RequestTriage.Status.DONE)
        self.assertEqual((self.triage.suggested_category, self.triage.latency_ms), (DEVOPS, 1234))
        self.assertEqual(self.triage.suggested_mentor, self.mentor)
        self.assertEqual(self.triage.model_name, ai.model_name())

    def test_run_triage_failure_is_recorded(self):
        with mock.patch.object(tasks, 'classify', side_effect=ai.TriageError('Ollama éteint')):
            tasks.run_triage(self.triage.pk)
        self.triage.refresh_from_db()
        self.assertEqual((self.triage.status, self.triage.error_message), (RequestTriage.Status.FAILED, 'Ollama éteint'))

    def test_unexpected_error_does_not_crash(self):
        with mock.patch.object(tasks, 'classify', side_effect=RuntimeError('boom')), self.assertLogs('mentor.tasks'):
            tasks.run_triage(self.triage.pk)
        self.triage.refresh_from_db()
        self.assertEqual(self.triage.status, RequestTriage.Status.FAILED)

    def test_done_triage_is_not_recomputed(self):
        RequestTriage.objects.filter(pk=self.triage.pk).update(status=RequestTriage.Status.DONE)
        with mock.patch.object(tasks, 'classify') as classify:
            tasks.run_triage(self.triage.pk)
        classify.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_enqueue_uses_thread_in_development(self):
        with mock.patch.object(tasks.threading, 'Thread') as thread:
            tasks.enqueue_triage(self.triage.pk)
        thread.return_value.start.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_enqueue_uses_celery_in_production(self):
        with mock.patch.object(tasks.triage_request, 'delay') as delay:
            tasks.enqueue_triage(self.triage.pk)
        delay.assert_called_once_with(self.triage.pk)

    def test_ensure_triages_only_for_pending_and_can_be_disabled(self):
        other = MentorRequest.objects.create(student=self.student, team=self.team, subject='Résolu',
                                             category='x', description='x', status=MentorRequest.Status.RESOLVED)
        fresh = MentorRequest.objects.create(student=self.student, team=self.team, subject='Nouveau',
                                             category='x', description='x')
        with mock.patch.dict('os.environ', {'MENTOR_AI_ENABLED': 'false'}):
            tasks.ensure_triages([fresh])
        self.assertFalse(RequestTriage.objects.filter(help_request=fresh).exists())
        with mock.patch.object(tasks, 'enqueue_triage') as enqueue, self.captureOnCommitCallbacks(execute=True):
            tasks.ensure_triages([fresh, other])
        self.assertTrue(RequestTriage.objects.filter(help_request=fresh).exists())
        self.assertFalse(RequestTriage.objects.filter(help_request=other).exists())
        enqueue.assert_called_once()


class TriageViewTests(MentorViewsTestBase):
    def test_queue_launches_analysis_after_commit(self):
        with mock.patch.object(tasks, 'enqueue_triage') as enqueue, self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(reverse('mentor:help_requests'))
        self.assertContains(response, 'Analyse IA en cours')
        enqueue.assert_called_once_with(self.pending.triage.pk)

    def done_triage(self, **fields):
        data = {'status': RequestTriage.Status.DONE, 'suggested_category': DEVOPS, 'suggested_urgency': 'normal',
                'summary': 'Crash du conteneur', 'latency_ms': 900}
        data.update(fields)
        return RequestTriage.objects.create(help_request=self.pending, **data)

    def test_status_endpoint_returns_rendered_suggestion(self):
        self.done_triage()
        response = self.client.get(reverse('mentor:triage_status'), {'ids': f'{self.pending.pk},abc'})
        item = response.json()['triages'][str(self.pending.pk)]
        self.assertEqual(item['status'], 'done')
        self.assertIn('Crash du conteneur', item['html'])
        # L'étudiant a indiqué « bloquant », l'IA estime « conseil » : l'écart est signalé.
        self.assertIn('IA estime', item['html'])
        # Le formulaire « Corriger » doit revenir à la file d'attente, pas au point d'accès JSON.
        self.assertIn(f'value="{reverse("mentor:help_requests")}"', item['html'])
        self.assertNotIn('triage-status', item['html'])

    def test_status_endpoint_keeps_safe_next_url(self):
        self.done_triage()
        page = reverse('mentor:help_requests') + '?view=pending'
        ok = self.client.get(reverse('mentor:triage_status'), {'ids': self.pending.pk, 'next': page})
        self.assertIn('value="/mentor/requests/?view=pending"', ok.json()['triages'][str(self.pending.pk)]['html'])
        evil = self.client.get(reverse('mentor:triage_status'), {'ids': self.pending.pk, 'next': 'https://evil.example'})
        self.assertNotIn('evil.example', evil.json()['triages'][str(self.pending.pk)]['html'])

    def test_status_hides_other_mentors_tickets(self):
        self.done_triage()
        self.take(self.pending)
        self.client.force_login(self.other_mentor)
        response = self.client.get(reverse('mentor:triage_status'), {'ids': str(self.pending.pk)})
        self.assertEqual(response.json()['triages'], {})

    def test_student_cannot_use_ai_endpoints(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('mentor:triage_status')).status_code, 403)
        self.assertEqual(self.client.get(reverse('mentor:ai_metrics')).status_code, 403)

    def test_correct_suggestion(self):
        triage = self.done_triage()
        self.client.post(reverse('mentor:triage_correct', args=[self.pending.pk]),
                         {'category': BACKEND, 'urgency': 'blocking'})
        triage.refresh_from_db()
        self.assertEqual((triage.corrected_category, triage.corrected_urgency), (BACKEND, 'blocking'))
        self.assertEqual(triage.corrected_by, self.mentor)

    def test_invalid_correction_is_ignored(self):
        triage = self.done_triage()
        self.client.post(reverse('mentor:triage_correct', args=[self.pending.pk]),
                         {'category': 'Cuisine', 'urgency': 'blocking'})
        triage.refresh_from_db()
        self.assertEqual(triage.corrected_category, '')

    def test_retry_only_failed(self):
        triage = self.done_triage(status=RequestTriage.Status.FAILED)
        with mock.patch.object(tasks, 'enqueue_triage') as enqueue, self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('mentor:triage_retry', args=[self.pending.pk]))
        triage.refresh_from_db()
        self.assertEqual(triage.status, RequestTriage.Status.PENDING)
        enqueue.assert_called_once_with(triage.pk)
        RequestTriage.objects.filter(pk=triage.pk).update(status=RequestTriage.Status.DONE)
        response = self.client.post(reverse('mentor:triage_retry', args=[self.pending.pk]))
        self.assertEqual(response.status_code, 404)

    def test_metrics_page_with_and_without_report(self):
        self.done_triage(corrected_category=DEVOPS, corrected_urgency='blocking', corrected_by=self.mentor)
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / 'report.json'
            with mock.patch('mentor.management.commands.evaluate_triage.REPORT_JSON', report_path):
                response = self.client.get(reverse('mentor:ai_metrics'))
                self.assertContains(response, "Aucun rapport d'évaluation")
                self.assertEqual(response.context['live']['category_agreement'], 100)
                self.assertEqual(response.context['live']['urgency_agreement'], 0)
                report = {
                    'generated_at': '2026-10-24T10:00:00', 'model': 'llama3.2', 'samples': 2, 'answered': 2,
                    'errors': [], 'cold_start_ms': 2000,
                    'latency': {'count': 1, 'mean_ms': 900, 'p50_ms': 900, 'p95_ms': 900, 'max_ms': 900},
                    'category': classification_report([DEVOPS, BACKEND], [DEVOPS, DEVOPS], ai.CATEGORIES),
                    'urgency': classification_report(['blocking', 'normal'], ['blocking', 'normal'], ai.URGENCIES),
                }
                report_path.write_text(json.dumps(report), encoding='utf-8')
                response = self.client.get(reverse('mentor:ai_metrics'))
        self.assertContains(response, 'matrice de confusion')
        self.assertContains(response, '0,500')


class EvaluateTriageCommandTests(TestCase):
    def test_command_writes_reports(self):
        dataset = [
            {'subject': 'Docker crash', 'description': 'x', 'category': DEVOPS, 'urgency': 'blocking'},
            {'subject': 'Migration', 'description': 'x', 'category': BACKEND, 'urgency': 'important'},
            {'subject': 'Ollama off', 'description': 'x', 'category': BACKEND, 'urgency': 'normal'},
        ]
        answers = [({'category': DEVOPS, 'urgency': 'blocking', 'summary': ''}, 2000),
                   ({'category': DEVOPS, 'urgency': 'important', 'summary': ''}, 1000),
                   ai.TriageError('timeout')]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'data.json').write_text(json.dumps(dataset), encoding='utf-8')
            with mock.patch('mentor.management.commands.evaluate_triage.classify', side_effect=answers), \
                    mock.patch('mentor.management.commands.evaluate_triage.REPORT_JSON', tmp / 'r.json'), \
                    mock.patch('mentor.management.commands.evaluate_triage.REPORT_MD', tmp / 'r.md'):
                call_command('evaluate_triage', dataset=str(tmp / 'data.json'), stdout=StringIO(), stderr=StringIO())
            report = json.loads((tmp / 'r.json').read_text(encoding='utf-8'))
            markdown = (tmp / 'r.md').read_text(encoding='utf-8')
        self.assertEqual((report['samples'], report['answered'], len(report['errors'])), (3, 2, 1))
        self.assertEqual(report['category']['accuracy'], 0.5)
        self.assertEqual(report['urgency']['accuracy'], 1.0)
        self.assertEqual(report['cold_start_ms'], 2000)
        self.assertIn('Matrice de confusion', markdown)

    def test_invalid_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.json'
            path.write_text(json.dumps([{'subject': 's', 'description': 'd', 'category': 'Cuisine',
                                         'urgency': 'normal'}]), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('evaluate_triage', dataset=str(path), stdout=StringIO())

    def test_default_dataset_is_valid(self):
        samples = json.loads((Path(ai.__file__).parent / 'ai_dataset' / 'triage_dataset.json')
                             .read_text(encoding='utf-8'))
        self.assertEqual(len(samples), 60)
        for sample in samples:
            self.assertIn(sample['category'], ai.CATEGORIES)
            self.assertIn(sample['urgency'], ai.URGENCIES)
