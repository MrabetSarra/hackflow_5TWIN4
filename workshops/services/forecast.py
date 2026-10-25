"""
workshops/services/forecast.py
================================
IA 3 — Prédiction de remplissage et des no-shows.

Stratégie :
  - Si ≥ 5 ateliers passés disponibles → entraîne un modèle Ridge ou
    RandomForest sur les features extraites.
  - Sinon → règle heuristique simple (fallback).

Features utilisées :
  hours_remaining   : heures avant le début
  fill_rate_now     : taux de remplissage actuel (0-1)
  weekday           : jour de la semaine (0=lundi)
  hour_of_day       : heure de début
  mode_enc          : encodage du mode (onsite=0, online=1, recorded=2)
  level_enc         : encodage du niveau (beginner=0, intermediate=1, advanced=2)

Sorties :
  fill_proba   : probabilité (0-1) que l'atelier soit complet
  noshow_proba : probabilité estimée de no-show
  alert        : message d'alerte textuel si fill_proba > 0.75

Aucune clé API requise.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

_MODE_ENC  = {'onsite': 0, 'online': 1, 'recorded': 2}
_LEVEL_ENC = {'beginner': 0, 'intermediate': 1, 'advanced': 2}


def _static_features(workshop) -> list[float]:
    """
    Vecteur de features indépendantes du moment présent.

    Important : ces features sont identiques pour un atelier passé et pour
    un atelier futur, ce qui rend l'entraînement cohérent avec la prédiction
    (les anciennes features « heures restantes » valaient toujours 0 pour
    les ateliers passés, ce qui rendait le modèle inexploitable).
    """
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
    Fallback heuristique quand pas assez de données historiques.
    Basé sur le taux actuel et le temps restant.
    """
    now = timezone.now()
    delta = workshop.starts_at - now
    hours_remaining = max(0.0, delta.total_seconds() / 3600)

    if workshop.capacity == 0:
        return {'fill_proba': 0.0, 'noshow_proba': 0.05, 'alert': None}

    fill_now = workshop.confirmed_count / workshop.capacity if workshop.capacity else 0.0

    # Projection linéaire : si on est déjà à X% avec T heures restantes,
    # on estime qu'on atteindra fill_now * (1 + coeff) à l'ouverture
    if hours_remaining > 0:
        speed = fill_now / max(1, 24 * 7 - hours_remaining)  # remplissage/heure
        projected = fill_now + speed * hours_remaining
    else:
        projected = fill_now

    fill_proba   = min(0.99, round(projected, 2))
    noshow_proba = 0.10 if workshop.mode == 'onsite' else 0.05

    alert = None
    if fill_proba > 0.75 and 0 <= hours_remaining < 24:
        alert = (
            f'⚠️ {round(fill_proba * 100)}% de risque que '
            f'«{workshop.title}» soit complet dans '
            f'{int(hours_remaining)}h — envisagez une session 2.'
        )

    return {
        'fill_proba':   fill_proba,
        'noshow_proba': noshow_proba,
        'alert':        alert,
    }


def _ml_forecast(workshop, past_workshops) -> dict:
    """
    Prédiction par modèle ML entraîné sur les ateliers passés.
    Utilise Ridge (rapide) avec fallback RandomForest si Ridge R²<0.
    """
    try:
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
        import numpy as np
    except ImportError:
        return _heuristic_forecast(workshop)

    X_train, y_fill, y_noshow = [], [], []

    for pw in past_workshops:
        if pw.capacity == 0:
            continue
        feat = _static_features(pw)
        actual_fill = min(1.0, max(0.0, pw.attendee_count / pw.capacity))
        noshow_rate = 1 - (pw.attendee_count / max(1, pw.confirmed_count))
        noshow_rate = min(1.0, max(0.0, noshow_rate))
        X_train.append(feat)
        y_fill.append(actual_fill)
        y_noshow.append(noshow_rate)

    if len(X_train) < 3:
        return _heuristic_forecast(workshop)

    try:
        import numpy as np
        X = np.array(X_train)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model_fill   = Ridge(alpha=1.0)
        model_noshow = Ridge(alpha=1.0)
        model_fill.fit(X_scaled, y_fill)
        model_noshow.fit(X_scaled, y_noshow)

        x_pred = scaler.transform([_static_features(workshop)])
        fill_proba   = float(np.clip(model_fill.predict(x_pred)[0], 0, 1))
        noshow_proba = float(np.clip(model_noshow.predict(x_pred)[0], 0, 1))

        alert = None
        delta = workshop.starts_at - timezone.now()
        hours_remaining = delta.total_seconds() / 3600
        if fill_proba > 0.75 and 0 <= hours_remaining < 48:
            alert = (
                f'⚠️ {round(fill_proba * 100)}% de risque que '
                f'«{workshop.title}» soit complet dans '
                f'{int(hours_remaining)}h.'
            )

        return {
            'fill_proba':   round(fill_proba, 2),
            'noshow_proba': round(noshow_proba, 2),
            'alert':        alert,
        }

    except Exception as exc:
        logger.warning('Erreur ML forecast : %s', exc)
        return _heuristic_forecast(workshop)


def forecast(workshop) -> dict:
    """
    Point d'entrée principal.
    Retourne un dict : {'fill_proba', 'noshow_proba', 'alert'}.
    """
    from workshops.models import Workshop as WS

    now = timezone.now()
    past = list(
        WS.objects.filter(ends_at__lt=now, capacity__gt=0)
        .exclude(pk=workshop.pk)
        .order_by('-ends_at')[:50]
    )

    if len(past) >= 5:
        return _ml_forecast(workshop, past)
    return _heuristic_forecast(workshop)
