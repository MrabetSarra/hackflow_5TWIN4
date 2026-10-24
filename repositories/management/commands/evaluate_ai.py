"""Evaluate repository secret scanning and task-generation metrics."""
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from repositories.ai import scan_secrets
from repositories.models import AIUsageLog
from student.ai_tasks import TaskSuggestionError, generate_tasks
from student.models import AITaskJob, TeamMembership


class Command(BaseCommand):
    help = 'Evaluate secret scanning and AI task-generation metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true', help='Call the configured live AI provider.')
        parser.add_argument('--output', default='', help='Report output path (defaults to reports/ai_metrics.md).')

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
        report = f'''# AI Evaluation Metrics

Generated: {timezone.now().isoformat()}
Task-generation evaluation mode: {mode}

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
'''
        output_path = Path(options['output']) if options['output'] else Path(settings.BASE_DIR) / 'reports' / 'ai_metrics.md'
        if not output_path.is_absolute():
            output_path = Path(settings.BASE_DIR) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding='utf-8')
        self.stdout.write(report)
        self.stdout.write(self.style.SUCCESS(f'Report saved to {output_path}'))
