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


def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL, temperature: float = 0.7, num_predict: int = 500) -> str | None:
    """
    Envoie un prompt à Ollama et retourne le texte généré, ou None en cas d'échec.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
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


# ---------------------------------------------------------------------------
# 1. Génération de titres d'atelier
# ---------------------------------------------------------------------------

def generate_workshop_titles(theme: str, audience: str = "", level: str = "Débutant") -> list[str]:
    """
    Génère 3 titres d'atelier accrocheurs à partir d'un thème.
    Retourne une liste de 3 titres, ou une liste par défaut en cas d'échec.
    """
    prompt = (
        f"Tu es un expert en formation professionnelle. Génère exactement 3 titres d'atelier "
        f"accrocheurs et professionnels en français pour un thème : '{theme}'.\n"
        f"Public cible : {audience or 'étudiants et professionnels'}\n"
        f"Niveau : {level}\n"
        f"Contraintes : chaque titre doit faire moins de 60 caractères, être clair et attrayant. "
        f"Réponds uniquement avec les 3 titres, un par ligne, sans numérotation ni texte supplémentaire."
    )

    generated = _ollama_generate(prompt, temperature=0.8)
    if generated:
        titles = [t.strip() for t in generated.split('\n') if t.strip()][:3]
        if len(titles) >= 2:
            return titles

    # Fallback statique
    return [
        f"Atelier : {theme}",
        f"Maîtriser {theme} : initiation pratique",
        f"{theme} : de la théorie à la pratique",
    ]


# ---------------------------------------------------------------------------
# 2. Génération d'objectifs pédagogiques
# ---------------------------------------------------------------------------

def generate_pedagogical_objectives(title: str, level: str = "Débutant", tags: list[str] | None = None) -> list[str]:
    """
    Génère 3 à 5 objectifs pédagogiques pour un atelier.
    Retourne une liste d'objectifs, ou une liste par défaut en cas d'échec.
    """
    tags_str = ", ".join(tags) if tags else "général"
    prompt = (
        f"Tu es un ingénieur pédagogique. Écris 4 objectifs pédagogiques clairs et mesurables "
        f"(verbes d'action : comprendre, réaliser, configurer, déployer… ) pour l'atelier : '{title}'.\n"
        f"Niveau : {level}\n"
        f"Tags thématiques : {tags_str}\n"
        f"Chaque objectif doit faire une seule ligne, commencer par un verbe d'action, et être réaliste. "
        f"Réponds uniquement avec les 4 objectifs, un par ligne, sans numérotation ni préambule."
    )

    generated = _ollama_generate(prompt, temperature=0.6)
    if generated:
        objectives = [o.strip() for o in generated.split('\n') if o.strip()][:5]
        if len(objectives) >= 2:
            return objectives

    # Fallback statique
    return [
        f"Comprendre les fondamentaux de {title}",
        f"Mettre en pratique les concepts abordés lors de l'atelier",
        f"Réaliser un projet concret appliquant les notions vues",
        f"Échanger avec l'intervenant sur les cas d'usage réels",
    ]


# ---------------------------------------------------------------------------
# 3. Génération de résumé automatique
# ---------------------------------------------------------------------------

def generate_workshop_summary(title: str, description: str, level: str = "Débutant") -> str:
    """
    Génère un court résumé (50-80 mots) d'un atelier pour l'affichage dans les cartes du catalogue.
    Retourne le résumé, ou une version tronquée de la description en cas d'échec.
    """
    desc_excerpt = description[:400] if description else title
    prompt = (
        f"Écris un résumé attrayant de 50 à 80 mots en français pour l'atelier suivant :\n"
        f"Titre : {title}\n"
        f"Niveau : {level}\n"
        f"Description : {desc_excerpt}\n"
        f"Ce résumé sera affiché sur une carte de catalogue. Il doit donner envie de s'inscrire. "
        f"Réponds uniquement par le résumé, sans titre ni introduction."
    )

    generated = _ollama_generate(prompt, temperature=0.6)
    if generated:
        return generated

    # Fallback : tronquer la description
    return desc_excerpt[:100] + ("…" if len(desc_excerpt) > 100 else "")


# ---------------------------------------------------------------------------
# 4. Explication de recommandation (IA personnalisée)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 5. Génération de questions de quiz
# ---------------------------------------------------------------------------

def generate_quiz_questions(title: str, description: str, level: str = "Débutant", num_questions: int = 5) -> list[dict]:
    """
    Génère des questions de quiz à choix multiples pour valider la compréhension
    d'un atelier après visionnage du replay.
    Retourne une liste de dicts : [{question, options, correct_index, explanation}, ...]
    """
    desc_excerpt = description[:500] if description else title
    prompt = (
        f"Tu es un formateur expert. Génère {num_questions} questions de quiz à choix multiples (QCM) "
        f"pour valider la compréhension de l'atelier : '{title}'.\n"
        f"Niveau : {level}\n"
        f"Contenu de l'atelier : {desc_excerpt}\n"
        f"Pour chaque question, fournis :\n"
        f"1. La question\n"
        f"2. 4 options de réponse (A, B, C, D)\n"
        f"3. L'index de la bonne réponse (0-3)\n"
        f"4. Une brève explication de la bonne réponse\n"
        f"Réponds uniquement avec un tableau JSON valide, sans texte avant ni après.\n"
        f"Format : [{{\"question\": \"...\", \"options\": [\"A\", \"B\", \"C\", \"D\"], \"correct\": 1, \"explication\": \"...\"}}, ...]"
    )

    generated = _ollama_generate(prompt, temperature=0.5, num_predict=800)
    if generated:
        try:
            # Extraire le JSON de la réponse
            start = generated.find('[')
            end = generated.rfind(']') + 1
            if start != -1 and end > start:
                data = json.loads(generated[start:end])
                if isinstance(data, list) and len(data) >= 2:
                    return data[:num_questions]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback statique
    return [
        {
            "question": f"Quel est l'objectif principal de l'atelier «{title}» ?",
            "options": ["Découvrir les concepts de base", "Se perfectionner", "Obtenir une certification", "Réseauter"],
            "correct": 0,
            "explication": "L'atelier vise principalement à introduire les concepts fondamentaux."
        },
        {
            "question": "Quel niveau est requis pour participer à cet atelier ?",
            "options": ["Débutant", "Intermédiaire", "Avancé", "Tous niveaux"],
            "correct": 0,
            "explication": f"L'atelier est de niveau {level}."
        },
    ]
