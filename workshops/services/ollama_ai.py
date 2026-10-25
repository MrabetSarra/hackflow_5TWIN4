"""
workshops/services/ollama_ai.py
===============================
IA générative locale via Ollama (modèle llama3.2).

Aucune clé API requise — fonctionne 100% hors ligne sur http://localhost:11434.
"""

from __future__ import annotations

import json
import logging
from urllib import request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 30  # secondes


def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL, temperature: float = 0.7) -> str | None:
    """
    Envoie un prompt à Ollama et retourne le texte généré, ou None en cas d'échec.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": 500,
        },
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
        logger.warning("Ollama indisponible ou erreur : %s", exc)
        return None


def generate_workshop_description(title: str, tags: list[str], speaker: str = "", level: str = "Débutant") -> str:
    """
    Génère une description d'atelier à partir du titre, des tags et du niveau.
    Retourne la description générée ou une description par défaut en cas d'échec.
    """
    tags_str = ", ".join(tags) if tags else "général"
    prompt = (
        f"Tu es un expert en formation professionnelle. Écris une description attrayante et professionnelle "
        f"(150-250 mots, en français) pour un atelier intitulé '{title}'.\n"
        f"Niveau : {level}\n"
        f"Tags thématiques : {tags_str}\n"
        f"Intervenant : {speaker or 'Non spécifié'}\n"
        f"La description doit présenter les objectifs, ce que les participants apprendront, et pourquoi c'est utile. "
        f"Écris uniquement la description, sans titre ni introduction."
    )

    generated = _ollama_generate(prompt)
    if generated:
        return generated

    # Fallback statique si Ollama est indisponible
    return (
        f"Participez à l'atelier «{title}» animé par {speaker or 'un expert'}. "
        f"Ce session de niveau {level.lower()} aborde les thématiques suivantes : {tags_str}. "
        f"Un moment d'apprentissage pratique et d'échange pour développer vos compétences."
    )


def explain_recommendation(workshop_title: str, matched_terms: list[str], user_profile: str) -> str:
    """
    Génère une explication personnalisée de pourquoi cet atelier est recommandé à l'étudiant.
    """
    terms_str = ", ".join(matched_terms) if matched_terms else "votre profil"
    prompt = (
        f"Explique en une phrase courte et chaleureuse (en français, maximum 25 mots) pourquoi l'atelier "
        f"'{workshop_title}' est recommandé à cet étudiant.\n"
        f"Compétences détectées chez l'étudiant : {user_profile[:200]}\n"
        f"Termes en commun avec l'atelier : {terms_str}\n"
        f"Réponds uniquement par l'explication, sans préambule."
    )

    generated = _ollama_generate(prompt, temperature=0.5)
    if generated:
        return generated

    if matched_terms:
        return f"Parce que tu maîtrises {terms_str}, cet atelier te correspond."
    return "Recommandé selon ton profil et tes centres d'intérêt."


def is_ollama_available() -> bool:
    """
    Vérifie qu'Ollama répond et que le modèle llama3.2 est disponible.
    """
    try:
        req = request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(OLLAMA_MODEL in m for m in models)
    except Exception:
        return False
