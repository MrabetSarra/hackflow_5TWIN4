"""
workshops/services/forecast.py
==============================
IA — Prédiction de remplissage et des no-shows.

Stratégie :
  1. Si Ollama est disponible (modèle llama3.2) → prédiction générative basée
     sur les caractéristiques de l'atelier (mode, niveau, capacité, jour, heure).
  2. Sinon → règle heuristique avec taux de base pour éviter d'afficher 0%.

Features utilisées :
  hours_remaining : heures avant le début
  fill_rate_now   : taux de remplissage actuel (0-1)
  weekday         : jour de la semaine (0=lundi)
  hour_of_day     : heure de début
  mode_enc        : encodage du mode (onsite=0, online=1, recorded=2)
  level_enc       : encodage du niveau (beginner=0, intermediate=1, advanced=2)

Sorties :
  fill_proba   : probabilité (0-1) que l'atelier soit complet
  noshow_proba : probabilité estimée de no-show
  alert        : message d'alerte textuel si fill_proba > 0.75

Aucune clé API requise — Ollama fonctionne 100% hors ligne sur localhost:11434.
"""

from __future__ import annotations

import json
import logging
from urllib import request
from urllib.error import URLError, HTTPError

from django.utils import timezone

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 5  # secondes (réduit pour ne pas bloquer le dashboard)

_MODE_ENC  = {'onsite': 0, 'online': 1, 'recorded': 2}
_LEVEL_ENC = {'beginner': 0, 'intermediate': 1, 'advanced': 2}

# Taux de remplissage de base pour un atelier neuf sans réservation
# (évite d'afficher 0% systématiquement)
BASELINE_FILL = 0.20


# ---------------------------------------------------------------------------
# Ollama — prédiction générative
# ---------------------------------------------------------------------------

def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL, temperature: float = 0.3) -> str | None:
    """Envoie un prompt à Ollama et retourne le texte généré, ou None."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 200},
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            return (result.get("response") or "").strip()
    except (URLError, HTTPError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Ollama indisponible pour la prévision IA : %s", exc)
        return None


def _ollama_available() -> bool:
    """Vérifie qu'Ollama répond et que le modèle llama3.2 est chargé."""
    try:
        req = request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(OLLAMA_MODEL in m for m in models)
    except Exception:
        return False


def _ollama_forecast(workshop) -> dict | None:
    """
    Demande à Ollama (llama3.2) une prédiction de remplissage pour l'atelier.
    Retourne un dict {'fill_proba', 'noshow_proba', 'alert'} ou None.
    """
    now = timezone.now()
    delta = workshop.starts_at - now
    hours_remaining = max(0.0, delta.total_seconds() / 3600)

    prompt = (
        "Tu es un analyste de données spécialisé dans l'événementiel et la formation. "
        "Estime le taux de remplissage (0 à 100%) et le taux de no-show (0 à 100%) "
        "pour un atelier avec les caractéristiques suivantes :\n"
        f"- Titre : {workshop.title}\n"
        f"- Mode : {workshop.mode} (présentiel / en ligne / vidéo enregistrée)\n"
        f"- Niveau : {getattr(workshop, 'level', 'débutant')}\n"
        f"- Capacité : {workshop.capacity or 'illimitée'} places\n"
        f"- Date/heure de début : {workshop.starts_at.strftime('%d/%m/%Y %H:%M')}\n"
        f"- Heures restantes avant le début : {int(hours_remaining)}h\n"
        f"- Réservations actuelles : {workshop.confirmed_count}\n"
        f"\nRéponds UNIQUEMENT au format JSON suivant, sans aucun texte avant ou après :\n"
        '{ "fill_proba": <nombre 0-100>, "noshow_proba": <nombre 0-100>, "raison": "explication courte en français" }'
    )

    generated = _ollama_generate(prompt)
    if not generated:
        return None

    # Extraire le JSON de la réponse (Ollama peut ajouter du texte autour)
    try:
        start = generated.find('{')
        end = generated.rfind('}') + 1
        if start == -1 or end == 0:
            return None
        data = json.loads(generated[start:end])
        fill = float(data.get('fill_proba', 0)) / 100.0
        noshow = float(data.get('noshow_proba', 5)) / 100.0
        fill = max(0.0, min(0.99, fill))
        noshow = max(0.0, min(0.99, noshow))

        alert = None
        if fill > 0.75 and 0 <= hours_remaining < 24:
            alert = (
                f'⚠️ {round(fill * 100)}% de risque que '
                f'«{workshop.title}» soit complet dans {int(hours_remaining)}h.'
            )

        return {
            'fill_proba': round(fill, 2),
            'noshow_proba': round(noshow, 2),
            'alert': alert,
            'source': 'ollama',
        }
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Réponse Ollama non parseable : %s", exc)
        return None


# ---------------------------------------------------------------------------
# Heuristique (fallback)
# ---------------------------------------------------------------------------

def _static_features(workshop) -> list[float]:
    duration = workshop.ends_at - workshop.starts_at
    duration_h = max(0.0, duration.total_seconds() / 3600)
    return [
        float(workshop.capacity or 0),
        float(workshop.starts_at.weekday()),
        float(workshop.starts_at.hour),
        float(_MODE_ENC.get(workshop.mode, 0)),
        float(_LEVEL_ENC.get(workshop.level, 0)),
        duration_h,
    ]


def _heuristic_forecast(workshop) -> dict:
    """
    Fallback heuristique. Applique un taux de base (20%) pour les ateliers
    sans réservation afin d'éviter d'afficher 0% systématiquement.
    """
    now = timezone.now()
    delta = workshop.starts_at - now
    hours_remaining = max(0.0, delta.total_seconds() / 3600)

    if workshop.capacity == 0:
        return {'fill_proba': 0.0, 'noshow_proba': 0.05, 'alert': None}

    fill_now = workshop.confirmed_count / workshop.capacity if workshop.capacity else 0.0

    # Taux de base pour atelier neuf (pas de réservation encore)
    if fill_now == 0:
        fill_now = BASELINE_FILL

    # Projection : le taux de remplissage augmente à mesure que l'atelier approche
    if hours_remaining > 0:
        # Facteur temps : influence maximale à 72h, puis stabilise
        time_factor = min(1.0, hours_remaining / 72.0)
        # On projette vers un remplissage cible de 80% si l'atelier est loin
        target_fill = 0.80
        projected = fill_now + (target_fill - fill_now) * time_factor * 0.4
    else:
        projected = fill_now

    fill_proba = min(0.99, round(projected, 2))
    noshow_proba = 0.10 if workshop.mode == 'onsite' else 0.05

    alert = None
    if fill_proba > 0.75 and 0 <= hours_remaining < 24:
        alert = (
            f'⚠️ {round(fill_proba * 100)}% de risque que '
            f'«{workshop.title}» soit complet dans {int(hours_remaining)}h — '
            f'envisagez une session 2.'
        )

    return {
        'fill_proba': fill_proba,
        'noshow_proba': noshow_proba,
        'alert': alert,
        'source': 'heuristic',
    }


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def forecast(workshop) -> dict:
    """
    Retourne un dict : {'fill_proba', 'noshow_proba', 'alert'}.
    Préfère Ollama si disponible, sinon fallback heuristique.
    """
    # 1. Essayer Ollama d'abord
    if _ollama_available():
        result = _ollama_forecast(workshop)
        if result is not None:
            return result
        logger.warning("Ollama disponible mais prédiction échouée, passage en heuristique.")

    # 2. Fallback heuristique corrigé
    return _heuristic_forecast(workshop)
