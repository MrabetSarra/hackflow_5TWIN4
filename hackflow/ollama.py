"""Shared request helpers for the configured Ollama-compatible endpoint."""

import json
import urllib.error
import urllib.request

from django.conf import settings


def request_headers():
    """Return JSON headers and optional proxy or Cloudflare Access auth."""
    headers = {'Content-Type': 'application/json'}
    token = getattr(settings, 'OLLAMA_PROXY_TOKEN', '').strip()
    if token:
        # Cloudflare Access can be configured to read a service token from
        # Authorization as a JSON object; preserve that value verbatim.
        if token.startswith('{'):
            headers['Authorization'] = token
        else:
            headers['Authorization'] = f'Bearer {token}'
    return headers


def chat_completion(payload, timeout, base_url=None):
    """Call /api/chat, retrying a missing feature model with the configured shared model."""
    endpoint = (base_url or getattr(settings, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
    requested_model = payload.get('model', '')
    fallback_model = getattr(settings, 'OLLAMA_MODEL', '')

    def send(model):
        body = dict(payload)
        body['model'] = model
        req = urllib.request.Request(
            f'{endpoint}/api/chat', data=json.dumps(body).encode('utf-8'),
            headers=request_headers(), method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))

    try:
        return send(requested_model)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or not fallback_model or fallback_model == requested_model:
            raise
        return send(fallback_model)
