"""
workshops/services/recommend.py
================================
Recommandeur d'ateliers.

Fonctionnement :
  1. Les ateliers passés, fermés ou expirés sont systématiquement écartés.
  2. Un score TF-IDF (scikit-learn) sert de base : profil étudiant
     (skills + specialty + bio) comparé au contenu des ateliers.
  3. Si Ollama (llama3.2) est disponible, un seul appel reclasse les
     ateliers et fournit des explications personnalisées.
  4. Le résultat du classement LLM est mis en cache quelques minutes.

Aucune clé API requise — fonctionne 100% hors ligne.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()

import hashlib
import logging
from functools import lru_cache

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

RECOMMENDATION_CACHE_TTL = 300  # secondes


# Le fit TF-IDF est la partie coûteuse : on le mutualise pour un même corpus
# d'ateliers. La clé est la tuple des documents, donc le cache s'invalide
# automatiquement dès qu'un titre/description/tag change.
@lru_cache(maxsize=16)
def _fit_corpus(documents: tuple[str, ...]):
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),
        max_features=5000,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(documents)
    return vectorizer, matrix


def _is_recommendable(workshop, now=None) -> bool:
    """False dès que l'atelier est passé, fermé ou que son replay a expiré."""
    now = now or timezone.now()

    if not workshop.is_open:
        return False
    if workshop.ends_at < now:
        return False
    if workshop.mode == workshop.Mode.RECORDED:
        if workshop.available_until and workshop.available_until < now:
            return False
        return True
    return workshop.starts_at > now


def _default_score(workshop, profile_skills: list[str]) -> int:
    """
    Score de repli quand scikit-learn est indisponible :
    correspondance simple entre les tags de l'atelier et les compétences.
    """
    tags = workshop.topic_tags if isinstance(workshop.topic_tags, list) else []
    profile_lower = {skill.lower() for skill in profile_skills}
    matches = sum(1 for tag in tags if str(tag).lower() in profile_lower)
    return min(100, matches * 25)


def _build_user_profile(user) -> str:
    """
    Construit un texte représentant le profil de l'étudiant.
    Exploite : skills (JSONField list), specialty, bio.
    Ajoute les compétences manquantes dans l'équipe si disponibles.
    """
    parts = []

    skills = user.skills if isinstance(user.skills, list) else []
    parts.extend(str(skill) for skill in skills)

    if getattr(user, 'specialty', None):
        parts.append(user.specialty)
    if getattr(user, 'bio', None):
        parts.append(user.bio)

    try:
        membership = user.team_memberships.select_related('team').first()
        if membership and membership.team.seeking_skill:
            parts.append(membership.team.seeking_skill)
    except Exception:
        pass

    return ' '.join(parts) if parts else 'python programming developer'


def _workshop_document(workshop) -> str:
    """Construit le document texte d'un atelier."""
    tags = workshop.topic_tags if isinstance(workshop.topic_tags, list) else []
    return ' '.join(str(tag) for tag in tags) + ' ' + workshop.description + ' ' + workshop.speaker_name


def _apply_tfidf(workshop_list, profile_text: str) -> bool:
    """Injecte ai_score/ai_reason via TF-IDF. Retourne False si sklearn manque."""
    try:
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        logger.warning('scikit-learn non installé : recommandations par score par défaut.')
        return False

    documents = tuple(_workshop_document(workshop) for workshop in workshop_list)

    try:
        tfidf, matrix = _fit_corpus(documents)
        profile_vector = tfidf.transform([profile_text])
        scores = cosine_similarity(profile_vector, matrix)[0]
        terms = tfidf.get_feature_names_out()
        profile_indices = set(profile_vector.nonzero()[1])

        for index, workshop in enumerate(workshop_list):
            raw_score = float(scores[index])
            workshop_indices = set(matrix[index].nonzero()[1])
            matched_terms = [
                terms[term] for term in workshop_indices & profile_indices
            ][:3]

            # Aucun score artificiel : un atelier sans aucun terme commun
            # obtient 0 et n'apparaît pas dans les recommandations.
            workshop.ai_score = max(0, min(99, round(raw_score * 100)))
            workshop.tfidf_score = workshop.ai_score
            if matched_terms:
                workshop.ai_reason = (
                    f'Parce que tu maîtrises {", ".join(matched_terms)}'
                )
            elif workshop.ai_score:
                workshop.ai_reason = 'Recommandé selon ton profil'
            else:
                workshop.ai_reason = 'Atelier suggéré pour découvrir de nouveaux thèmes'
    except ValueError:
        # Corpus vide ou uniquement des stop-words.
        for workshop in workshop_list:
            workshop.ai_score = 0
            workshop.ai_reason = 'Atelier suggéré pour découvrir de nouveaux thèmes'
        return True

    return True


def _apply_default(workshop_list, user) -> None:
    profile_skills = user.skills if isinstance(user.skills, list) else []
    for workshop in workshop_list:
        score = _default_score(workshop, profile_skills)
        workshop.ai_score = score
        workshop.ai_reason = (
            'Recommandé selon votre profil et centres d\'intérêt'
            if score > 0 else 'Atelier suggéré pour découvrir de nouveaux thèmes'
        )


def _ranking_cache_key(user, profile_text: str, workshop_list) -> str:
    seed_parts = [str(getattr(user, 'pk', '')), profile_text]
    for workshop in workshop_list:
        seed_parts.append(
            f'{workshop.pk}:{workshop.starts_at.isoformat()}:'
            f'{workshop.title}:{hashlib.md5((workshop.description or "").encode()).hexdigest()}'
        )
    digest = hashlib.md5('|'.join(seed_parts).encode('utf-8')).hexdigest()
    return f'workshops:reco:v2:{digest}'


def _ollama_ranking(user, profile_text: str, workshop_list):
    """Un seul appel Ollama, avec cache. Retourne None si indisponible."""
    cache_key = _ranking_cache_key(user, profile_text, workshop_list)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from .ollama_ai import is_ollama_available, rank_workshops_for_user
        if not is_ollama_available():
            return None
        ranking = rank_workshops_for_user(profile_text, workshop_list)
    except Exception:
        logger.exception('Classement Ollama indisponible pour les ateliers')
        return None

    if ranking:
        cache.set(cache_key, ranking, RECOMMENDATION_CACHE_TTL)
    return ranking


def _apply_ranking(workshop_list, ranking) -> None:
    by_id = {workshop.pk: workshop for workshop in workshop_list}
    for item in ranking:
        workshop = by_id.get(item.get('id'))
        if not workshop:
            continue
        # Ollama reclasse les ateliers pertinents mais ne peut pas promouvoir
        # un atelier sans aucun terme commun avec le profil (score TF-IDF nul).
        if getattr(workshop, 'tfidf_score', 0) <= 0:
            continue
        workshop.ai_score = int(item.get('score', 0))
        reason = (item.get('reason') or '').strip()
        if reason:
            workshop.ai_reason = reason


def recommend(user, workshops, top_n: int = 6) -> list:
    """
    Retourne une liste d'ateliers à venir triés par pertinence décroissante.

    Chaque atelier reçoit deux attributs injectés :
      .ai_score  (int 0-100)
      .ai_reason (str)
    """
    now = timezone.now()
    workshop_list = [
        workshop for workshop in workshops
        if _is_recommendable(workshop, now)
    ]

    if not workshop_list:
        return []

    profile_text = _build_user_profile(user)

    if _apply_tfidf(workshop_list, profile_text):
        ranking = _ollama_ranking(user, profile_text, workshop_list)
        if ranking:
            _apply_ranking(workshop_list, ranking)
    else:
        _apply_default(workshop_list, user)

    workshop_list.sort(key=lambda w: getattr(w, 'ai_score', 0), reverse=True)
    return workshop_list[:top_n] if len(workshop_list) > top_n else workshop_list
