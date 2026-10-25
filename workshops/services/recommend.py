"""
workshops/services/recommend.py
================================
IA 1 — Recommandeur d'ateliers basé sur TF-IDF (scikit-learn).

Fonctionnement :
  1. Le profil de l'étudiant (skills + specialty + bio) forme un document pivot.
  2. Chaque atelier forme un document (topic_tags + description).
  3. TfidfVectorizer calcule la similarité cosinus entre le profil et chaque atelier.
  4. On extrait les termes croisés pour construire une explication lisible.
  5. Un bonus est appliqué si l'atelier couvre des compétences recherchées
     par l'équipe de l'étudiant (seeking_skill).

Aucune clé API requise — fonctionne 100% hors ligne.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

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


def _reset_scores(workshops):
    for workshop in workshops:
        workshop.ai_score = 0
        workshop.ai_reason = ''


def _build_user_profile(user) -> str:
    """
    Construit un texte représentant le profil de l'étudiant.
    Exploite : skills (JSONField list), specialty, bio.
    Ajoute les compétences manquantes dans l'équipe si disponibles.
    """
    parts = []

    # Compétences personnelles
    skills = user.skills if isinstance(user.skills, list) else []
    parts.extend(skills)

    # Spécialité et bio
    if getattr(user, 'specialty', None):
        parts.append(user.specialty)
    if getattr(user, 'bio', None):
        parts.append(user.bio)

    # Compétences cherchées par l'équipe (bonus de pertinence)
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
    return ' '.join(tags) + ' ' + workshop.description + ' ' + workshop.speaker_name


def recommend(user, workshops, top_n: int = 6) -> list:
    """
    Retourne une liste d'ateliers triés par pertinence décroissante.

    Chaque atelier reçoit deux attributs injectés :
      .ai_score  (int 0-100)
      .ai_reason (str)

    En cas d'erreur (sklearn absent), retourne les ateliers sans score.
    """
    workshop_list = list(workshops)

    if not workshop_list:
        return []

    try:
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        logger.warning('scikit-learn non installé : recommandations désactivées.')
        _reset_scores(workshop_list)
        return workshop_list

    profile_text = _build_user_profile(user)
    documents = tuple(_workshop_document(w) for w in workshop_list)

    try:
        tfidf, matrix = _fit_corpus(documents)
        profile_vector = tfidf.transform([profile_text])
        scores = cosine_similarity(profile_vector, matrix)[0]
        terms = tfidf.get_feature_names_out()

        # Indices présents dans le profil
        profile_indices = set(profile_vector.nonzero()[1])

        for i, workshop in enumerate(workshop_list):
            raw_score = float(scores[i])

            # Termes croisés → explication
            ws_indices = set(matrix[i].nonzero()[1])
            matched_terms = [
                terms[j] for j in ws_indices & profile_indices
            ][:3]

            # Pas de bonus artificiel : 0 % signifie réellement 0 %.
            workshop.ai_score = min(99, round(raw_score * 100))
            if workshop.ai_score and matched_terms:
                workshop.ai_reason = (
                    f'Parce que tu maîtrises {", ".join(matched_terms)}'
                )
            elif workshop.ai_score:
                workshop.ai_reason = 'Recommandé selon ton profil'
            else:
                workshop.ai_reason = ''

    except Exception as exc:
        logger.error('Erreur recommandation TF-IDF : %s', exc)
        _reset_scores(workshop_list)

    # Tri décroissant par score
    workshop_list.sort(key=lambda w: getattr(w, 'ai_score', 0), reverse=True)
    return workshop_list[:top_n] if len(workshop_list) > top_n else workshop_list
