"""Benchmark Ollama-backed AI calls without writing prompts or responses to disk."""
import json
import math
import time
import urllib.error
import urllib.request
import json
from datetime import timedelta
from types import SimpleNamespace
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Measure latency for representative Ollama-backed AI features.'

    def add_arguments(self, parser):
        parser.add_argument('--runs', type=int, default=5, help='Calls per feature (default: 5).')
        parser.add_argument('--output', default='docs/ai_eval/benchmark.json')

    @staticmethod
    def _stats(values):
        ordered = sorted(values)
        if not ordered:
            return {key: None for key in ('mean_ms', 'median_ms', 'p95_ms', 'min_ms', 'max_ms')}
        def percentile(p):
            return ordered[max(0, math.ceil(p * len(ordered)) - 1)]
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        return {
            'mean_ms': round(sum(ordered) / len(ordered), 2), 'median_ms': round(median, 2),
            'p95_ms': percentile(.95), 'min_ms': min(ordered), 'max_ms': max(ordered),
        }

    def handle(self, *args, **options):
        if options['runs'] < 1 or options['runs'] > 100:
            raise CommandError('--runs must be between 1 and 100.')
        base = getattr(settings, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
        report = {
            'generated_at': timezone.now().isoformat(), 'mode': 'real_ollama_only',
            'runs_requested_per_feature': options['runs'], 'features': {},
        }
        try:
            from hackflow.ollama import request_headers
            body = json.dumps({
                'model': getattr(settings, 'OLLAMA_MODEL', 'llama3.2'),
                'messages': [{'role': 'user', 'content': 'Réponds uniquement par OK.'}],
                'stream': False, 'options': {'num_predict': 1},
            }).encode('utf-8')
            health_request = urllib.request.Request(
                f'{base}/api/chat', data=body, headers=request_headers(), method='POST',
            )
            with urllib.request.urlopen(health_request, timeout=15) as response:
                json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, OSError):
            report['status'] = 'À mesurer'
            report['reason'] = 'Ollama is not reachable at the configured OLLAMA_BASE_URL; no mock timings were recorded.'
            for feature in (
                'mentor_triage', 'admin_copilot', 'announcement_draft', 'project_evaluation',
                'workshop_titles', 'workshop_forecast', 'repository_suggestion',
            ):
                report['features'][feature] = {
                    'status': 'À mesurer', 'runs': 0, 'attempts': 0, 'successful_runs': 0,
                    'timeout_rate': None,
                }
        else:
            from dashboard_admin.announcement_generator import generate_announcement_draft
            from dashboard_admin.copilot import ask_copilot
            from dashboard_admin.project_evaluation import analyze_project_submission
            from mentor.ai import classify
            from repositories.ai import _call_provider
            from workshops.services.ollama_ai import _ollama_generate as workshop_generate
            from workshops.services.forecast import _ollama_forecast as workshop_forecast
            from django.utils import timezone as django_timezone
            from student.models import Announcement

            now = django_timezone.now()
            team = SimpleNamespace(
                name='Équipe d’évaluation', project_name='', category='', project_pitch='',
                hackathon=SimpleNamespace(name='HackFlow évaluation'),
            )
            submission = SimpleNamespace(
                file=None, team=team, project_name='', category='', description='',
                milestone=SimpleNamespace(title='Livrable', description=''), github_url='', demo_url='',
                video_url='', get_status_display=lambda: 'soumis',
            )
            workshop = SimpleNamespace(
                capacity=20, confirmed_count=5, starts_at=now + timedelta(days=3),
                ends_at=now + timedelta(days=3, hours=2), mode='onsite', level='beginner', title='Atelier test',
            )
            repo_provider = getattr(settings, 'REPOSITORY_AI_PROVIDER', 'ollama')
            audience = Announcement.Audience.choices[0][0]
            probes = {
                'mentor_triage': lambda: classify(
                    'API renvoie une erreur 500', 'Depuis la migration, le endpoint principal échoue.'),
                'admin_copilot': lambda: ask_copilot(
                    'Résume ces faits et propose une action.', {'équipes': [], 'risques': []}),
                'announcement_draft': lambda: generate_announcement_draft(
                    audience=audience, topic='Rappel : compléter votre profil.', tone='professionnel', message_type='rappel'),
                'project_evaluation': lambda: analyze_project_submission(submission),
                'workshop_titles': lambda: workshop_generate(
                    'Propose trois titres de formation en français sur la sécurité des API.'),
                'workshop_forecast': lambda: workshop_forecast(workshop),
            }
            if repo_provider == 'ollama':
                probes['repository_suggestion'] = lambda: _call_provider(
                    'Réponds en français : propose une amélioration concise pour une API de réservation.')
            report['status'] = 'mesuré'
            if repo_provider != 'ollama':
                report['features']['repository_suggestion'] = {
                    'status': 'À mesurer', 'runs': 0, 'attempts': 0, 'successful_runs': 0, 'timeout_rate': None,
                    'reason': 'REPOSITORY_AI_PROVIDER is not Ollama; this command measures Ollama only.',
                }
            for feature, probe in probes.items():
                durations, attempt_durations, timeouts, failures = [], [], 0, 0
                failure_types = {}
                failure_status_codes = {}
                for _ in range(options['runs']):
                    started = time.perf_counter()
                    try:
                        result = probe()
                        if result is None or result == '':
                            raise RuntimeError('The Ollama feature returned no model output.')
                        durations.append(round((time.perf_counter() - started) * 1000))
                    except Exception as exc:
                        failures += 1
                        failure_types[type(exc).__name__] = failure_types.get(type(exc).__name__, 0) + 1
                        cause = exc
                        visited = set()
                        while cause is not None and id(cause) not in visited:
                            visited.add(id(cause))
                            code = getattr(cause, 'code', None)
                            if isinstance(code, int):
                                key = f'HTTP_{code}'
                                failure_status_codes[key] = failure_status_codes.get(key, 0) + 1
                            cause = cause.__cause__ or cause.__context__
                        reason = getattr(exc, 'reason', None)
                        if isinstance(exc, TimeoutError) or 'timeout' in type(exc).__name__.lower() or isinstance(reason, TimeoutError):
                            timeouts += 1
                    finally:
                        attempt_durations.append(round((time.perf_counter() - started) * 1000))
                report['features'][feature] = {
                    'status': 'mesuré' if durations else 'échec_fournisseur',
                    'runs': len(durations), 'attempts': len(attempt_durations), 'successful_runs': len(durations),
                    **self._stats(durations),
                    'timeout_rate': round(timeouts / len(attempt_durations), 4), 'failure_count': failures,
                    'failure_types': failure_types, 'failure_status_codes': failure_status_codes,
                }
        output = Path(options['output'])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        self.stdout.write(f'Report saved to {output}')
