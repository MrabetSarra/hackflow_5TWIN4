"""Client Gemini avec modèle principal et modèle de secours (fallback automatique).

La clé API n'est lue que dans l'environnement (variable GEMINI_API_KEY, chargée depuis .env par settings.py).
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = 'https://generativelanguage.googleapis.com/v1beta/models'
DEFAULT_PRIMARY_MODEL = 'gemini-3.5-flash'
DEFAULT_FALLBACK_MODEL = 'gemini-3.5-flash-lite'


class GeminiError(Exception):
    """Erreur dont le message est destiné à l'utilisateur final (jamais de clé ni de détail technique)."""

    def __init__(self, message, meta=None):
        super().__init__(message)
        self.meta = meta or {}


class GeminiNotConfigured(GeminiError):
    pass


def configuration():
    return {
        'api_key': os.environ.get('GEMINI_API_KEY', '').strip(),
        'primary': os.environ.get('GEMINI_MODEL', DEFAULT_PRIMARY_MODEL).strip() or DEFAULT_PRIMARY_MODEL,
        'fallback': os.environ.get('GEMINI_FALLBACK_MODEL', DEFAULT_FALLBACK_MODEL).strip() or DEFAULT_FALLBACK_MODEL,
        'timeout': _int_env('GEMINI_TIMEOUT', 40),
    }


def _int_env(name, default):
    try:
        return max(5, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _http_error_message(exc):
    code = exc.code
    if code in (401, 403):
        return 'La clé API Gemini est refusée ou n’a pas les droits nécessaires.'
    if code == 400:
        try:
            detail = json.loads(exc.read().decode('utf-8')).get('error', {}).get('message', '')
        except (ValueError, AttributeError, UnicodeDecodeError):
            detail = ''
        if 'API key' in detail:
            return 'La clé API Gemini est invalide.'
        return 'Gemini a refusé la requête (paramètres invalides).'
    if code == 404:
        return 'Le modèle Gemini demandé est introuvable.'
    if code == 429:
        return 'Le quota Gemini est atteint. Réessayez dans un instant.'
    if code >= 500:
        return 'Gemini est momentanément indisponible.'
    return f'Gemini a répondu avec une erreur ({code}).'


def _call(model, prompt, api_key, timeout, temperature=0.6, max_tokens=4096):
    """Seul point d'appel réseau : retourne le texte brut de la réponse du modèle."""
    generation = {
        'temperature': temperature,
        'maxOutputTokens': max_tokens,
        'responseMimeType': 'application/json',
    }
    if '2.5' in model:
        generation['thinkingConfig'] = {'thinkingBudget': 0}
    body = json.dumps({
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': generation,
    }).encode('utf-8')
    request = urllib.request.Request(
        f'{API_ROOT}/{urllib.parse.quote(model, safe="")}:generateContent', data=body, method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise GeminiError(_http_error_message(exc)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GeminiError('Impossible de joindre Gemini (réseau indisponible ou délai dépassé).') from None
    except ValueError:
        raise GeminiError('La réponse de Gemini est illisible.') from None

    if payload.get('promptFeedback', {}).get('blockReason'):
        raise GeminiError('Gemini a bloqué cette demande pour des raisons de sécurité.')
    try:
        parts = payload['candidates'][0]['content']['parts']
        text = ''.join(part.get('text', '') for part in parts)
    except (KeyError, IndexError, TypeError):
        raise GeminiError('Gemini n’a renvoyé aucune réponse exploitable.') from None
    if not text.strip():
        raise GeminiError('Gemini a renvoyé une réponse vide.')
    return text


def parse_json(text):
    cleaned = (text or '').strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        raise GeminiError('La réponse de l’IA n’a pas le format attendu.') from None


def generate_json(prompt, validator, temperature=0.6):
    """Interroge le modèle principal puis, en cas d'échec, le modèle de secours.

    Retourne (données validées, métadonnées). Lève GeminiError avec les métadonnées si tout échoue.
    """
    config = configuration()
    started = time.perf_counter()
    meta = {
        'model': '', 'fallback_used': False, 'primary_error': '', 'input_chars': len(prompt), 'output_chars': 0,
        'latency_ms': 0,
    }
    if not config['api_key']:
        raise GeminiNotConfigured(
            'L’assistant IA n’est pas configuré : ajoutez GEMINI_API_KEY dans le fichier .env puis redémarrez le serveur.', meta)

    models = [config['primary']]
    if config['fallback'] and config['fallback'] != config['primary']:
        models.append(config['fallback'])

    last_error = 'Aucune réponse de l’IA.'
    for index, model in enumerate(models):
        try:
            text = _call(model, prompt, config['api_key'], config['timeout'], temperature)
            data = validator(parse_json(text))
        except (GeminiError, ValueError) as exc:
            last_error = str(exc) or 'Réponse invalide.'
            if index == 0:
                meta['primary_error'] = last_error[:300]
            continue
        meta.update(
            model=model, fallback_used=index > 0, output_chars=len(text),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return data, meta

    meta['latency_ms'] = round((time.perf_counter() - started) * 1000)
    meta['model'] = models[-1]
    meta['fallback_used'] = len(models) > 1
    raise GeminiError(f'{last_error} Le modèle de secours n’a pas non plus abouti.' if len(models) > 1 else last_error, meta)
