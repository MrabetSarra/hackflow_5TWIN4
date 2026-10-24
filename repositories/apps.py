from django.apps import AppConfig
import logging
import shutil
import socket
from urllib.parse import urlparse


class RepositoriesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'repositories'

    def ready(self):
        logger = logging.getLogger('repositories')
        if shutil.which('git') is None:
            logger.warning('Git executable was not found. Repository Git operations will be unavailable.')

        from django.conf import settings
        provider = str(settings.REPOSITORY_AI_PROVIDER).strip().lower()
        endpoints = {
            'anthropic': ('https://api.anthropic.com', settings.ANTHROPIC_API_KEY),
            'openai': ('https://api.openai.com', settings.OPENAI_API_KEY),
            'ollama': (settings.OLLAMA_BASE_URL, None),
        }
        endpoint = endpoints.get(provider)
        if endpoint is None:
            logger.warning('The configured AI provider is custom; availability will be checked when requested.')
            return
        url, key = endpoint
        if provider in {'anthropic', 'openai'} and not key:
            logger.warning('AI provider %s has no API key configured; AI suggestions will be unavailable.', provider)
            return
        try:
            parsed = urlparse(url)
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            with socket.create_connection((parsed.hostname, port), timeout=1):
                pass
        except (OSError, ValueError, TypeError):
            logger.warning('AI provider %s is unreachable; AI suggestions will be unavailable.', provider)
