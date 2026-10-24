"""Shared request helpers for the configured Ollama-compatible endpoint."""

from django.conf import settings


def request_headers():
    """Return JSON headers and optional bearer auth for a protected proxy."""
    headers = {'Content-Type': 'application/json'}
    token = getattr(settings, 'OLLAMA_PROXY_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers
