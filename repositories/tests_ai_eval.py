import json
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest import TestCase, mock

from django.conf import settings

from hackflow.ai_telemetry import timed_ai
from hackflow.ollama import chat_completion
from django.test import override_settings


class AITelemetryTests(TestCase):
    def test_logs_outcome_and_duration_without_arguments(self):
        @timed_ai('test_feature')
        def private_call(secret):
            return secret

        with self.assertLogs('hackflow.ai', level='INFO') as captured:
            self.assertEqual(private_call('do-not-log-this'), 'do-not-log-this')
        self.assertIn('outcome=success', captured.output[0])
        self.assertNotIn('do-not-log-this', captured.output[0])

    def test_evaluation_dataset_and_prompt_rubric_have_required_sizes(self):
        root = Path(settings.BASE_DIR)
        dataset = json.loads((root / 'tests/ai_eval/dataset.json').read_text(encoding='utf-8'))
        prompts = json.loads((root / 'tests/ai_eval/generative_prompts.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(dataset), 30)
        self.assertGreaterEqual(len(prompts['cases']), 10)
        self.assertIn('60 demandes', (root / 'tests/ai_eval/README.md').read_text(encoding='utf-8'))

    @override_settings(OLLAMA_MODEL='installed-model', OLLAMA_PROXY_TOKEN='')
    @mock.patch('urllib.request.urlopen')
    def test_ollama_chat_retries_configured_model_when_feature_model_is_missing(self, urlopen):
        missing = urllib.error.HTTPError('http://test.invalid', 404, 'missing', {}, BytesIO())
        response = mock.MagicMock()
        response.__enter__.return_value = BytesIO(b'{"message":{"content":"ok"}}')
        urlopen.side_effect = [missing, response]

        result = chat_completion({'model': 'optional-model', 'messages': []}, timeout=1, base_url='http://test.invalid')

        self.assertEqual(result['message']['content'], 'ok')
        retry_body = json.loads(urlopen.call_args_list[1].args[0].data.decode('utf-8'))
        self.assertEqual(retry_body['model'], 'installed-model')
