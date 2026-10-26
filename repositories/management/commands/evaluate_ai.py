"""Evaluate repository secret scanning and task-generation metrics."""
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone
from mentor.ai import CATEGORIES, URGENCIES, TriageError, classify, model_name
from mentor.metrics import classification_report

from repositories.ai import scan_secrets
from repositories.models import AIUsageLog
from student.ai_tasks import TaskSuggestionError, generate_tasks
from student.models import AITaskJob, TeamMembership


class Command(BaseCommand):
    help = 'Evaluate secret scanning and AI task-generation metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true', help='Call the configured live AI provider.')
        parser.add_argument('--output', default='', help='Report output path (defaults to reports/ai_metrics.md).')
        parser.add_argument('--skip-triage', action='store_true', help='Do not call Ollama for the labeled mentor dataset.')
        parser.add_argument('--run-generative', action='store_true', help='Run the 10 real qualitative prompts through their Ollama-backed services.')

    @staticmethod
    def _percentile(values, percentile):
        ordered = sorted(int(value) for value in values)
        if not ordered:
            return None
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]

    def handle(self, *args, **options):
        fixture_path = Path(settings.BASE_DIR) / 'repositories' / 'tests' / 'fixtures' / 'secrets_dataset.json'
        dataset = json.loads(fixture_path.read_text(encoding='utf-8'))
        matrix = {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0}
        for sample in dataset:
            actual = bool(sample['contains_secret'])
            predicted = bool(scan_secrets(str(sample['text'])))
            if actual and predicted:
                matrix['tp'] += 1
            elif not actual and predicted:
                matrix['fp'] += 1
            elif not actual and not predicted:
                matrix['tn'] += 1
            else:
                matrix['fn'] += 1
        precision = matrix['tp'] / (matrix['tp'] + matrix['fp']) if matrix['tp'] + matrix['fp'] else 0
        recall = matrix['tp'] / (matrix['tp'] + matrix['fn']) if matrix['tp'] + matrix['fn'] else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0

        total_proposed = AITaskJob.objects.aggregate(total=Sum('proposed_count'))['total'] or 0
        total_accepted = AITaskJob.objects.aggregate(total=Sum('accepted_count'))['total'] or 0
        acceptance_rate = total_accepted / total_proposed if total_proposed else 0

        sample_result = 'Skipped: no team membership exists in this database.'
        membership = TeamMembership.objects.select_related('team', 'user').order_by('pk').first()
        if membership:
            sample_job = SimpleNamespace(
                team=membership.team, user=membership.user,
                prompt='Add resilient API request validation and helpful error responses.',
            )
            fixed_response = json.dumps([{
                'title': 'Validate request payloads',
                'description': 'Validate required API fields and return helpful errors.',
                'category': 'Backend', 'priority': 'normal',
            }])
            try:
                if options['live']:
                    suggested = generate_tasks(sample_job)
                    sample_result = f'Live provider returned {len(suggested)} valid task suggestion(s).'
                else:
                    with patch('repositories.ai._call_provider', return_value=(fixed_response, {'input_tokens': 20, 'output_tokens': 15})), \
                         patch('repositories.ai._provider_metadata', return_value=('mocked', 'deterministic-fixture')):
                        suggested = generate_tasks(sample_job, count_against_limit=False)
                    sample_result = f'Mocked provider returned {len(suggested)} valid task suggestion(s).'
            except TaskSuggestionError as exc:
                sample_result = f'Generation failed cleanly: {str(exc)}'

        job_latencies = list(AITaskJob.objects.exclude(latency_ms=0).values_list('latency_ms', flat=True))
        usage_latencies = list(AIUsageLog.objects.filter(feature='task_generation').values_list('latency_ms', flat=True))

        def display(value):
            return f'{value} ms' if value is not None else 'n/a'

        mode = 'live provider' if options['live'] else 'deterministic mocked provider'
        evaluation = self._evaluate_triage(options['skip_triage'])
        qualitative = self._run_generative() if options['run_generative'] else self._qualitative_template()
        generative_evaluated = sum(1 for case in qualitative if case.get('status') == 'real')
        results = {
            'generated_at': timezone.now().isoformat(),
            'classification': evaluation,
            'generative_quality': {
                'status': 'real_outputs_collected_human_review_required' if generative_evaluated else 'À mesurer',
                'rubric_source': 'tests/ai_eval/generative_prompts.json',
                'sample_count': len(qualitative),
                'cases': qualitative,
                'evaluated_outputs': generative_evaluated,
                'automatic_summary': self._automatic_summary(qualitative),
                'note': 'Human scores remain null until a reviewer completes relevance, correctness, format, and language ratings.',
            },
            'deterministic_secret_scanner': {
                'status': 'measured_rule_based', 'source': 'repositories/tests/fixtures/secrets_dataset.json',
                'samples': len(dataset), 'confusion_matrix': matrix,
                'precision': round(precision, 3), 'recall': round(recall, 3), 'f1': round(f1, 3),
            },
            'task_generation_probe': {
            'status': (
                'skipped' if sample_result.startswith('Skipped:')
                else 'mocked' if not options['live'] else 'real_provider'
            ),
                'result': sample_result,
                'warning': 'Mocked output is not an AI measurement.' if not options['live'] else '',
            },
        }
        ai_results = Path(settings.BASE_DIR) / 'docs' / 'ai_eval' / 'results.json'
        ai_results.parent.mkdir(parents=True, exist_ok=True)
        ai_results.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        if evaluation.get('status') in {'real', 'partial_real'}:
            self._save_confusion_images(evaluation)

        report = f'''# AI Evaluation Metrics

Generated: {timezone.now().isoformat()}
Task-generation evaluation mode: {mode}

Mentor classification evaluation: {evaluation.get('status', 'À mesurer')}
Generative qualitative prompts: {generative_evaluated}/{len(qualitative)} real outputs collected; human scores are not prefilled.
Structured results: `docs/ai_eval/results.json`

## Secret scanner

Fixture: `repositories/tests/fixtures/secrets_dataset.json` ({len(dataset)} labeled samples)

| Metric | Value |
|---|---:|
| True positives | {matrix['tp']} |
| False positives | {matrix['fp']} |
| True negatives | {matrix['tn']} |
| False negatives | {matrix['fn']} |
| Precision | {precision:.3f} |
| Recall | {recall:.3f} |
| F1 | {f1:.3f} |

## Task generation

| Metric | Value |
|---|---:|
| AI jobs recorded | {AITaskJob.objects.count()} |
| Proposed tasks | {total_proposed} |
| Accepted tasks | {total_accepted} |
| Acceptance rate | {acceptance_rate:.3f} |
| Job latency p50 | {display(self._percentile(job_latencies, 0.50))} |
| Job latency p95 | {display(self._percentile(job_latencies, 0.95))} |
| AI usage latency p50 | {display(self._percentile(usage_latencies, 0.50))} |
| AI usage latency p95 | {display(self._percentile(usage_latencies, 0.95))} |
| Provider sample | {sample_result} |

The default run uses a fixed mocked provider response. Use `--live` to contact the configured provider.
The mocked task-generation result is a software-path check only, never a model-quality measurement.
'''
        output_path = Path(options['output']) if options['output'] else Path(settings.BASE_DIR) / 'reports' / 'ai_metrics.md'
        if not output_path.is_absolute():
            output_path = Path(settings.BASE_DIR) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding='utf-8')
        self.stdout.write(report)
        self.stdout.write(self.style.SUCCESS(f'Report saved to {output_path}'))
        self.stdout.write(f'AI evaluation JSON saved to {ai_results}')

    def _evaluate_triage(self, skip):
        dataset_path = Path(settings.BASE_DIR) / 'tests' / 'ai_eval' / 'dataset.json'
        samples = json.loads(dataset_path.read_text(encoding='utf-8'))
        report = {
            'status': 'À mesurer', 'mode': 'real_ollama_only', 'model': model_name(),
            'dataset': 'tests/ai_eval/dataset.json', 'sample_count': len(samples),
            'answered': 0, 'errors': 0,
        }
        if skip:
            report['reason'] = 'Skipped by --skip-triage.'
            return report
        true_category, pred_category, true_urgency, pred_urgency = [], [], [], []
        errors = 0
        for sample in samples:
            try:
                prediction, _latency = classify(sample['subject'], sample['description'])
            except TriageError:
                errors += 1
                # The same provider/model/schema is used for every sample. Stop early if
                # the first inference cannot be made; do not report empty-set scores as 0.
                if errors >= 1 and not true_category:
                    report.update({
                        'status': 'À mesurer', 'errors': errors,
                        'reason': 'Ollama did not return a valid classification; no mock predictions were counted.',
                    })
                    return report
                continue
            true_category.append(sample['category'])
            pred_category.append(prediction['category'])
            true_urgency.append(sample['urgency'])
            pred_urgency.append(prediction['urgency'])
        report.update({'answered': len(true_category), 'errors': errors})
        if true_category:
            report.update({
                'status': 'real' if not errors else 'partial_real',
                'category': classification_report(true_category, pred_category, CATEGORIES),
                'urgency': classification_report(true_urgency, pred_urgency, URGENCIES),
            })
        else:
            report.update({
                'status': 'À mesurer',
                'reason': 'The endpoint responded to the health check but returned no valid classification for the dataset.',
            })
        return report

    @staticmethod
    def _qualitative_template():
        path = Path(settings.BASE_DIR) / 'tests' / 'ai_eval' / 'generative_prompts.json'
        source = json.loads(path.read_text(encoding='utf-8'))
        fields = ('relevance', 'correctness', 'format_validity', 'language')
        return [{
            **case, 'human_scores': {field: None for field in fields},
            'automatic_checks': {'valid_json': None, 'schema_compliant': None, 'empty_answer': None},
            'status': 'À mesurer',
        } for case in source['cases']]

    def _run_generative(self):
        """Run the authored cases through the production service call for each feature."""
        source_path = Path(settings.BASE_DIR) / 'tests' / 'ai_eval' / 'generative_prompts.json'
        cases = json.loads(source_path.read_text(encoding='utf-8'))['cases']
        from dashboard_admin.announcement_generator import generate_announcement_draft
        from dashboard_admin.copilot import ask_copilot
        from dashboard_admin.project_evaluation import analyze_project_submission
        from repositories.ai import _call_provider
        from student.models import Announcement

        now_team = SimpleNamespace(
            name='Équipe évaluation', project_name='', category='', project_pitch='Prototype pédagogique.',
            hackathon=SimpleNamespace(name='HackFlow — jeu de test'),
        )
        output = []
        for case in cases:
            item = {
                **case,
                'human_scores': {key: None for key in ('relevance', 'correctness', 'format_validity', 'language')},
                'automatic_checks': {'valid_json': None, 'schema_compliant': None, 'empty_answer': None},
                'status': 'À mesurer',
            }
            try:
                feature = case['feature']
                if feature == 'admin_copilot':
                    response = ask_copilot(case['prompt'], {'teams': [], 'deadlines': [], 'projects': []})
                    required = ('answer', 'announcement_title', 'announcement_body')
                    empty = not str(response.get('answer', '')).strip()
                    schema_ok = all(isinstance(response.get(key), str) for key in required)
                    encoded = json.dumps(response, ensure_ascii=False)
                elif feature == 'announcement_draft':
                    response = generate_announcement_draft(
                        audience=Announcement.Audience.ALL, topic=case['prompt'],
                        tone='professionnel', message_type='annonce',
                    )
                    schema_ok = all(isinstance(response.get(key), str) and response[key].strip()
                                    for key in ('title', 'body'))
                    empty = not schema_ok
                    encoded = json.dumps(response, ensure_ascii=False)
                elif feature == 'project_evaluation':
                    submission = SimpleNamespace(
                        file=None, team=now_team, project_name='Atelier solidaire', category='Éducation',
                        description=case['prompt'], milestone=SimpleNamespace(title='Prototype', description='Démo'),
                        github_url='', demo_url='', video_url='', get_status_display=lambda: 'soumis',
                    )
                    response = analyze_project_submission(submission)
                    required = ('summary', 'objectives', 'technologies', 'use_cases', 'deliverables',
                                'rubric_review', 'jury_questions', 'missing_evidence')
                    schema_ok = all(key in response for key in required)
                    empty = not str(response.get('summary', '')).strip()
                    encoded = json.dumps(response, ensure_ascii=False)
                elif feature == 'repository_suggestion':
                    if getattr(settings, 'REPOSITORY_AI_PROVIDER', 'ollama') != 'ollama':
                        item.update(status='À mesurer', reason='Configured repository provider is not Ollama.')
                        output.append(item)
                        continue
                    response, _usage = _call_provider(case['prompt'])
                    schema_ok = None  # Repository suggestions are prose, not a JSON contract.
                    empty = not bool((response or '').strip())
                    encoded = response or ''
                else:
                    item.update(status='À mesurer', reason='No production evaluator is registered for this feature.')
                    output.append(item)
                    continue

                valid_json = True
                try:
                    json.loads(encoded if isinstance(encoded, str) else json.dumps(encoded))
                except (TypeError, ValueError):
                    valid_json = False
                item.update(
                    status='real', automatic_checks={
                        'valid_json': valid_json if feature != 'repository_suggestion' else None,
                        'schema_compliant': schema_ok,
                        'empty_answer': bool(empty),
                    },
                )
            except Exception as exc:
                item.update(status='échec', error_type=type(exc).__name__)
            output.append(item)
        return output

    @staticmethod
    def _automatic_summary(cases):
        checked_json = [case['automatic_checks']['valid_json'] for case in cases
                        if case['automatic_checks']['valid_json'] is not None]
        checked_schema = [case['automatic_checks']['schema_compliant'] for case in cases
                          if case['automatic_checks']['schema_compliant'] is not None]
        checked_empty = [case['automatic_checks']['empty_answer'] for case in cases
                         if case['automatic_checks']['empty_answer'] is not None]
        def rate(values, predicate):
            return round(sum(1 for value in values if predicate(value)) / len(values), 4) if values else None
        return {
            'valid_json_rate': rate(checked_json, bool), 'valid_json_count': len(checked_json),
            'schema_compliance_rate': rate(checked_schema, bool), 'schema_count': len(checked_schema),
            'empty_answer_rate': rate(checked_empty, bool), 'answer_count': len(checked_empty),
        }

    @staticmethod
    def _save_confusion_images(evaluation):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            return
        output = Path(settings.BASE_DIR) / 'docs' / 'ai_eval'
        for key in ('category', 'urgency'):
            section = evaluation[key]
            fig, axis = plt.subplots(figsize=(9, 7))
            axis.imshow(section['confusion_matrix'], cmap='Blues')
            axis.set_xticks(range(len(section['labels'])), labels=section['labels'], rotation=45, ha='right')
            axis.set_yticks(range(len(section['labels'])), labels=section['labels'])
            axis.set_xlabel('Classe prédite')
            axis.set_ylabel('Classe réelle')
            axis.set_title(f'Matrice de confusion — {key}')
            for row_index, row in enumerate(section['confusion_matrix']):
                for column_index, value in enumerate(row):
                    axis.text(column_index, row_index, str(value), ha='center', va='center')
            fig.tight_layout()
            fig.savefig(output / f'confusion_matrix_{key}.png', dpi=160)
            plt.close(fig)
