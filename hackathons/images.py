"""Génération de bannière par Stable Diffusion via l'API d'inférence Hugging Face.

Le jeton n'est lu que dans l'environnement (HF_API_TOKEN, chargé depuis .env par settings.py).
"""
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

API_ROOT = 'https://router.huggingface.co/hf-inference/models'
DEFAULT_MODEL = 'stabilityai/stable-diffusion-3-medium-diffusers'
GENERATED_DIR = 'hackathons/banners/generated/'
GENERATED_NAME_RE = r'^hackathons/banners/generated/[0-9a-f]{32}\.jpg$'
BANNER_SIZE = (1280, 720)


class ImageError(Exception):
    """Message destiné à l'utilisateur final (jamais de jeton ni de détail technique)."""


def configuration():
    try:
        timeout = max(10, int(os.environ.get('HF_IMAGE_TIMEOUT', 90)))
    except ValueError:
        timeout = 90
    return {
        'token': os.environ.get('HF_API_TOKEN', '').strip(),
        'fallback': os.environ.get('HF_IMAGE_FALLBACK', 'pollinations').strip().lower() == 'pollinations',
        'model': os.environ.get('HF_IMAGE_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        'timeout': timeout,
    }


def build_prompt(title, track='', summary='', instructions=''):
    parts = [f'Wide cinematic banner illustration for a technology hackathon named "{title}".']
    if track:
        parts.append(f'Theme: {track}.')
    if summary:
        parts.append(f'Context: {summary}.')
    if instructions:
        parts.append(f'Style hints: {instructions}.')
    parts.append('Modern, vibrant colors, digital art, detailed, professional, no text, no letters, no logo.')
    return ' '.join(parts)[:900]


def _http_error_message(exc):
    code = exc.code
    if code in (401, 403):
        return 'Le jeton Hugging Face est refusé ou n’a pas la permission « Inference Providers ».'
    if code == 402:
        return 'Le crédit gratuit Hugging Face est épuisé.'
    if code in (404, 410):
        return 'Le modèle d’image demandé n’est pas disponible. Changez HF_IMAGE_MODEL dans le .env.'
    if code == 429:
        return 'Le quota Hugging Face est atteint. Réessayez dans un instant.'
    if code == 503:
        return 'Le modèle d’image se charge ou est surchargé. Réessayez dans une minute.'
    if code >= 500:
        return 'Hugging Face est momentanément indisponible.'
    return f'Hugging Face a répondu avec une erreur ({code}).'


def _request_image(prompt, config):
    body = json.dumps({'inputs': prompt}).encode('utf-8')
    request = urllib.request.Request(
        f'{API_ROOT}/{urllib.parse.quote(config["model"], safe="/")}', data=body, method='POST',
        headers={'Authorization': f'Bearer {config["token"]}', 'Content-Type': 'application/json', 'Accept': 'image/png'},
    )
    try:
        with urllib.request.urlopen(request, timeout=config['timeout']) as response:
            return response.read(15 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise ImageError(_http_error_message(exc)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ImageError('Impossible de joindre Hugging Face (réseau indisponible ou délai dépassé).') from None


def _to_banner(raw):
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError('Hugging Face n’a pas renvoyé une image exploitable.') from None
    image = image.convert('RGB')
    target_w, target_h = BANNER_SIZE
    scale = max(target_w / image.width, target_h / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (image.width - target_w) // 2, (image.height - target_h) // 2
    image = image.crop((left, top, left + target_w, top + target_h))
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=88, optimize=True)
    return out.getvalue()


def _request_fallback(prompt, config):
    """Secours gratuit sans clé (Pollinations) quand Hugging Face est indisponible ou sans crédit."""
    url = (f'https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt, safe="")}'
           f'?width={BANNER_SIZE[0]}&height={BANNER_SIZE[1]}&nologo=true&model=flux')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'HackFlow'}), timeout=config['timeout']) as response:
            return response.read(15 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ImageError('Le service de secours de génération d’image est indisponible.') from None


def generate_banner(prompt):
    """Génère l'image, l'enregistre dans le stockage média et retourne son nom relatif."""
    config = configuration()
    try:
        if not config['token']:
            raise ImageError('La génération d’image n’est pas configurée : ajoutez HF_API_TOKEN dans le fichier .env puis redémarrez le serveur.')
        raw = _request_image(prompt, config)
    except ImageError as primary:
        if not config['fallback']:
            raise
        try:
            raw = _request_fallback(prompt, config)
        except ImageError as secondary:
            raise ImageError(f'{primary} {secondary}') from None
    data = _to_banner(raw)
    return default_storage.save(f'{GENERATED_DIR}{uuid.uuid4().hex}.jpg', ContentFile(data))
