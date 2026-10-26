"""
workshops/services/ollama_ai.py
===============================
IA générative locale via Ollama (modèle llama3.2).

Aucune clé API requise — fonctionne 100% hors ligne sur http://localhost:11434.
"""

from __future__ import annotations

import json
import logging
import re
from urllib import request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 30  # secondes

_OPTION_PREFIX_RE = re.compile(r'^\s*[A-Da-d][\)\.:-]\s*')


def _ollama_generate(
    prompt: str,
    model: str = OLLAMA_MODEL,
    temperature: float = 0.7,
    num_predict: int = 500,
    timeout: int | None = None,
) -> str | None:
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
        with request.urlopen(req, timeout=timeout or OLLAMA_TIMEOUT) as resp:
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
# 1 bis. Génération de description d'atelier
# ---------------------------------------------------------------------------

def generate_workshop_description(title: str, tags: list[str] | None = None,
                                  speaker: str = "", level: str = "Débutant") -> str:
    """
    Rédige une description d'atelier (120-180 mots) à partir du titre.
    Retourne une description de repli si Ollama est indisponible.
    """
    tags_str = ", ".join(tags) if tags else "non précisés"
    prompt = (
        f"Tu es un responsable pédagogique. Rédige une description attractive et concrète "
        f"en français (120 à 180 mots) pour l'atelier suivant :\n"
        f"Titre : {title}\n"
        f"Intervenant : {speaker or 'à préciser'}\n"
        f"Niveau : {level}\n"
        f"Thématiques : {tags_str}\n"
        f"La description doit présenter le contenu, le déroulé et les bénéfices pour les "
        f"participants. Réponds uniquement par la description, sans titre ni préambule."
    )

    generated = _ollama_generate(prompt, temperature=0.7, num_predict=450)
    if generated:
        return generated

    return (
        f"Cet atelier « {title} » s'adresse à un public de niveau {level.lower()} "
        f"et aborde les thématiques suivantes : {tags_str}. "
        f"Au programme : démonstrations, mise en pratique guidée et temps d'échange "
        f"avec l'intervenant pour repartir avec des compétences directement réutilisables."
    )


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
# 4 bis. Classement personnalisé d'ateliers (un seul appel Ollama)
# ---------------------------------------------------------------------------

def rank_workshops_for_user(user_profile: str, workshops,
                            max_candidates: int = 15) -> list[dict] | None:
    """
    Demande à llama3.2 de classer les ateliers pour un profil étudiant.

    Retourne [{id, score, reason}, ...] ou None si Ollama échoue.
    Un seul appel réseau, quel que soit le nombre d'ateliers.
    """
    candidates = []
    for workshop in list(workshops)[:max_candidates]:
        tags = workshop.topic_tags if isinstance(workshop.topic_tags, list) else []
        candidates.append({
            'id': workshop.pk,
            'titre': workshop.title,
            'niveau': workshop.get_level_display(),
            'mode': workshop.get_mode_display(),
            'tags': tags,
            'description': (workshop.description or '')[:300],
        })

    if not candidates:
        return None

    prompt = (
        f"Tu es un conseiller pédagogique. Voici le profil d'un étudiant :\n"
        f"{user_profile[:800]}\n\n"
        f"Voici les ateliers à venir :\n"
        f"{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"Classe ces ateliers par pertinence pour cet étudiant. Attribue à chacun un score "
        f"de 0 à 100 (0 = aucun intérêt, 100 = parfaitement adapté) et une raison courte "
        f"en français (20 mots maximum) expliquant le lien avec son profil.\n"
        f"Réponds uniquement avec un tableau JSON valide, sans texte avant ni après.\n"
        f'Format : [{{"id": 12, "score": 87, "reason": "..."}}]'
    )

    token_budget = min(2000, max(500, len(candidates) * 90))
    generated = _ollama_generate(
        prompt, temperature=0.2, num_predict=token_budget, timeout=90)
    payload = _extract_json(generated or '')

    if isinstance(payload, dict):
        payload = (payload.get('recommandations')
                   or payload.get('recommendations')
                   or payload.get('ateliers') or [])
    if not isinstance(payload, list):
        return None

    valid_ids = {workshop.pk for workshop in list(workshops)[:max_candidates]}
    ranking = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            workshop_id = int(item.get('id'))
        except (TypeError, ValueError):
            continue
        if workshop_id not in valid_ids:
            continue
        try:
            score = int(round(float(item.get('score', 0))))
        except (TypeError, ValueError):
            score = 0
        ranking.append({
            'id': workshop_id,
            'score': min(100, max(0, score)),
            'reason': str(item.get('reason') or item.get('raison') or '').strip(),
        })

    return ranking or None


# ---------------------------------------------------------------------------
# 5. Génération de questions de quiz
# ---------------------------------------------------------------------------

def _extract_json(text: str):
    """Extrait le premier objet/tableau JSON d'une réponse LLM bavarde."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)

    for opening, closing in (('[', ']'), ('{', '}')):
        start = cleaned.find(opening)
        end = cleaned.rfind(closing)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _coerce_options(item: dict) -> list[str]:
    """Récupère 4 options, que le JSON utilise une liste, un dict A-D ou option_a..d."""
    raw = item.get('options', item.get('reponses', item.get('choices')))
    values: list = []

    if isinstance(raw, dict):
        normalized_keys = {
            str(key).lower().replace('option_', '').replace('option', ''): value
            for key, value in raw.items()
        }
        if all(key in normalized_keys for key in 'abcd'):
            values = [normalized_keys[key] for key in 'abcd']
        elif raw and all(str(key).isdigit() for key in raw):
            values = [raw[key] for key in sorted(raw, key=lambda x: int(x))]
        else:
            values = list(raw.values())
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = [
            item.get('option_a', item.get('optionA', item.get('A'))),
            item.get('option_b', item.get('optionB', item.get('B'))),
            item.get('option_c', item.get('optionC', item.get('C'))),
            item.get('option_d', item.get('optionD', item.get('D'))),
        ]

    options = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        options.append(_OPTION_PREFIX_RE.sub('', text))

    while len(options) < 4:
        options.append(f'Option {len(options) + 1}')
    return options[:4]


def _coerce_correct_index(value, options: list[str]) -> int:
    """Accepte 2, "2", "B", "b." ou le texte exact de la bonne réponse."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return min(3, max(0, value))
    if isinstance(value, float) and value.is_integer():
        return min(3, max(0, int(value)))
    if isinstance(value, (list, tuple)) and value:
        return _coerce_correct_index(value[0], options)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return min(3, max(0, int(text)))
        letter = text.upper()[:1]
        if letter in 'ABCD':
            return 'ABCD'.index(letter)
        for index, option in enumerate(options):
            if text.lower() == option.strip().lower():
                return index
    return 0


def _normalize_quiz_item(item, source_options: list[str] | None = None) -> dict | None:
    """Normalise une question générée vers le format WorkshopQuiz."""
    if not isinstance(item, dict):
        return None

    question = str(
        item.get('question') or item.get('question_text') or item.get('intitule') or ''
    ).strip()
    if not question:
        return None

    options = _coerce_options(item)
    if source_options and isinstance(source_options, (list, tuple)):
        source = [_OPTION_PREFIX_RE.sub('', str(o).strip()) for o in source_options]
        if len(source) >= 4:
            options = source[:4]

    correct_value = item.get(
        'correct_index',
        item.get('correct', item.get('bonne_reponse', item.get('answer'))),
    )
    explanation = str(
        item.get('explanation') or item.get('explication')
        or item.get('rationale') or ''
    ).strip()

    return {
        'question': question,
        'options': options,
        'correct_index': _coerce_correct_index(correct_value, options),
        'explanation': explanation,
    }


def generate_quiz_questions(title: str, description: str, level: str = "Débutant",
                            num_questions: int = 5,
                            tags: list[str] | None = None) -> list[dict]:
    """
    Génère des questions de quiz à choix multiples à partir du contenu
    réel de l'atelier (titre, description, tags, niveau).

    Retourne une liste de dicts : [{question, options, correct_index, explanation}, ...]
    """
    try:
        num_questions = max(1, min(20, int(num_questions)))
    except (TypeError, ValueError):
        num_questions = 5

    desc_excerpt = (description or title)[:1200]
    tags_str = ", ".join(tags) if tags else "non précisés"
    prompt = (
        f"Tu es un formateur expert. À partir du contenu de l'atelier ci-dessous, "
        f"génère exactement {num_questions} questions de quiz à choix multiples (QCM) "
        f"en français pour vérifier la compréhension réelle des participants.\n\n"
        f"TITRE : {title}\n"
        f"NIVEAU : {level}\n"
        f"THÉMATIQUES : {tags_str}\n"
        f"DESCRIPTION : {desc_excerpt}\n\n"
        f"Règles :\n"
        f"- Les questions portent sur le contenu décrit (pas de questions génériques).\n"
        f"- Chaque question a exactement 4 options plausibles, une seule correcte.\n"
        f"- Varie la position de la bonne réponse (0, 1, 2 ou 3).\n"
        f"- Ajoute une explication courte de la bonne réponse.\n"
        f"Réponds uniquement avec un tableau JSON valide, sans texte avant ni après.\n"
        f'Format : [{{"question": "...", "options": ["...", "...", "...", "..."], '
        f'"correct_index": 1, "explanation": "..."}}]'
    )

    token_budget = min(3000, max(700, num_questions * 260))
    generated = _ollama_generate(
        prompt, temperature=0.4, num_predict=token_budget, timeout=90)

    payload = _extract_json(generated or '')
    if isinstance(payload, dict):
        payload = payload.get('questions') or payload.get('quiz') or []

    if isinstance(payload, list):
        normalized = []
        for item in payload:
            question = _normalize_quiz_item(item)
            if question:
                normalized.append(question)
            if len(normalized) >= num_questions:
                break
        if normalized:
            return normalized

    # Repli statique : des questions exploitables même sans Ollama.
    fallback = [
        {
            "question": f"Quel est l'objectif principal de l'atelier « {title} » ?",
            "options": [
                "Découvrir et mettre en pratique les concepts abordés",
                "Préparer un entretien d'embauche",
                "Rédiger un business plan",
                "Configurer un serveur de production",
            ],
            "correct_index": 0,
            "explanation": "L'atelier vise d'abord la découverte et la pratique du sujet.",
        },
        {
            "question": "Quel est le niveau recommandé pour cet atelier ?",
            "options": [level, "Expert confirmé", "Direction générale", "Aucun prérequis technique"],
            "correct_index": 0,
            "explanation": f"Le niveau annoncé pour cet atelier est « {level} ».",
        },
        {
            "question": "Quelle est la meilleure façon de profiter de l'atelier ?",
            "options": [
                "Lire uniquement les diapositives",
                "Participer et pratiquer les exercices proposés",
                "Attendre le replay sans réserver",
                "Mémoriser le programme sans le tester",
            ],
            "correct_index": 1,
            "explanation": "La pratique guidée est au cœur d'un atelier efficace.",
        },
    ]
    return fallback[:num_questions]


# ---------------------------------------------------------------------------
# 6. Suggestion d'options pour une question saisie par l'organisateur
# ---------------------------------------------------------------------------

def suggest_quiz_options(question: str, title: str = "",
                         description: str = "", level: str = "Débutant") -> dict | None:
    """
    Propose 4 options et la bonne réponse pour une question déjà rédigée
    par l'admin ou le mentor, en s'appuyant sur le contenu de l'atelier.

    Retourne {options, correct_index, explanation} ou None si Ollama échoue.
    """
    question = (question or '').strip()
    if not question:
        return None

    context = (description or title)[:1000]
    prompt = (
        f"Tu es un formateur expert. Un organisateur a rédigé cette question de quiz :\n"
        f"QUESTION : {question}\n\n"
        f"Atelier concerné : {title or 'non précisé'}\n"
        f"Niveau : {level}\n"
        f"Contenu de l'atelier : {context or 'non fourni'}\n\n"
        f"Propose exactement 4 options de réponse plausibles (une seule correcte), "
        f"identifie l'index de la bonne réponse (0 à 3) et rédige une explication courte.\n"
        f"Réponds uniquement avec un objet JSON valide, sans texte avant ni après.\n"
        f'Format : {{"options": ["...", "...", "...", "..."], "correct_index": 2, '
        f'"explanation": "..."}}'
    )

    generated = _ollama_generate(prompt, temperature=0.4, num_predict=450)
    payload = _extract_json(generated or '')

    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        return None

    options = _coerce_options(payload)
    correct_value = payload.get(
        'correct_index', payload.get('correct', payload.get('bonne_reponse')))
    explanation = str(
        payload.get('explanation') or payload.get('explication') or '').strip()

    return {
        'options': options,
        'correct_index': _coerce_correct_index(correct_value, options),
        'explanation': explanation,
    }
