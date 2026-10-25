"""
workshops/services/schedule.py
================================
IA 2 — Optimiseur d'emploi du temps.

Algorithme glouton :
  1. On part des ateliers scorés par recommend().
  2. On filtre ceux sans conflit avec les réservations existantes de l'étudiant.
  3. On applique une pénalité si l'atelier chevauche une deadline Milestone.
  4. On retourne les top 3 combinaisons optimales.

Aucune clé API requise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from django.utils import timezone


def _overlaps(ws, other_booking) -> bool:
    """Vérifie si un atelier chevauche une réservation existante."""
    ws_start = ws.starts_at
    ws_end   = ws.ends_at
    ob_start = other_booking.workshop.starts_at
    ob_end   = other_booking.workshop.ends_at
    # Chevauchement si pas (ws_end <= ob_start ou ws_start >= ob_end)
    return not (ws_end <= ob_start or ws_start >= ob_end)


def _deadline_penalty(ws, milestones) -> float:
    """
    Réduit le score si l'atelier se tient dans les 6h avant une deadline.
    Pénalité : 0.3 (30% de réduction).
    """
    for ms in milestones:
        delta = ms.due_at - ws.starts_at
        if timezone.timedelta(0) <= delta <= timezone.timedelta(hours=6):
            return 0.3
    return 0.0


def optimise_schedule(user, workshops, top_n: int = 3) -> list:
    """
    Retourne jusqu'à top_n ateliers formant un planning sans conflit.

    Chaque atelier reçoit :
      .schedule_score  (float)
      .schedule_reason (str)

    Paramètres
    ----------
    user      : instance User (accounts.User)
    workshops : QuerySet ou liste d'ateliers (avec .ai_score si disponible)
    top_n     : nombre de créneaux à retenir
    """
    from workshops.models import Booking

    # Réservations confirmées actuelles
    confirmed = list(
        Booking.objects.filter(
            user=user,
            status__in=['confirmed', 'attended'],
        ).select_related('workshop')
    )

    # Deadlines de l'équipe
    milestones = []
    try:
        from student.models import TeamMembership, Milestone
        membership = TeamMembership.objects.filter(user=user).first()
        if membership:
            milestones = list(
                Milestone.objects.filter(
                    hackathon=membership.team.hackathon
                ).order_by('due_at')
            )
    except Exception:
        pass

    now = timezone.now()
    result = []
    chosen_slots = []  # ateliers déjà sélectionnés (pour anti-conflit entre eux)

    for ws in workshops:
        if ws.starts_at < now:
            continue  # passé

        # Conflit avec réservations existantes
        conflict_booking = next(
            (b for b in confirmed if _overlaps(ws, b)), None
        )
        if conflict_booking:
            ws.schedule_reason = (
                f'Conflit avec «{conflict_booking.workshop.title}»'
            )
            ws.schedule_score = 0.0
            continue

        # Conflit avec ateliers déjà sélectionnés dans ce planning
        conflict_chosen = next(
            (c for c in chosen_slots
             if not (ws.ends_at <= c.starts_at or ws.starts_at >= c.ends_at)),
            None,
        )
        if conflict_chosen:
            continue  # on skip sans marquer

        # Score de base (ai_score si disponible, sinon 50)
        base = getattr(ws, 'ai_score', 50) / 100.0

        # Pénalité deadline
        penalty = _deadline_penalty(ws, milestones)
        score = round(base * (1 - penalty), 3)

        ws.schedule_score = score
        ws.schedule_reason = (
            '✅ Aucun conflit dans ton planning'
            if not penalty
            else '⚠️ Proche d\'une deadline — prévoir du temps'
        )

        chosen_slots.append(ws)
        result.append(ws)

        if len(result) >= top_n:
            break

    return result
