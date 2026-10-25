"""Shared request helpers for the configured Ollama-compatible endpoint."""

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
