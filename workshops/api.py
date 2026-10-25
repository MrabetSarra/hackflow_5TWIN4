"""
workshops/api.py
================
Endpoints JSON (AJAX) du module Ateliers.

GET /workshops/api/recommend/
  → Liste des 6 ateliers recommandés pour l'utilisateur courant.
    Retourne : [{id, title, slug, ai_score, ai_reason, mode, starts_at, seats_left}, ...]

GET /workshops/api/<pk>/seats/
  → Nombre de places restantes en temps réel pour un atelier.
    Retourne : {id, capacity, confirmed, seats_left, waitlist}
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import Workshop

logger = logging.getLogger(__name__)


@login_required
@require_GET
def api_recommend(request):
    """Retourne les recommandations IA pour l'utilisateur courant (JSON)."""
    try:
        from .services.recommend import recommend
        workshops = list(
            Workshop.objects.filter(is_open=True)
            .select_related('created_by')
            .order_by('starts_at')
        )
        recommended = [
            w for w in recommend(request.user, workshops, top_n=6)
            if getattr(w, 'ai_score', 0) > 0
        ]
        data = [
            {
                'id':       w.pk,
                'title':    w.title,
                'slug':     w.slug,
                'mode':     w.mode,
                'mode_display': w.get_mode_display(),
                'level':    w.level,
                'starts_at': w.starts_at.isoformat(),
                'seats_left': w.seats_left,
                'ai_score':  getattr(w, 'ai_score', None),
                'ai_reason': getattr(w, 'ai_reason', ''),
                'url':      w.get_absolute_url(),
            }
            for w in recommended
        ]
        return JsonResponse({'recommendations': data, 'count': len(data)})

    except Exception:
        # Ne jamais exposer un message d'exception interne au client.
        logger.exception('Erreur API recommandations ateliers')
        return JsonResponse({
            'error': 'Recommandations temporairement indisponibles.',
            'recommendations': [],
        }, status=503)


@require_GET
def api_seats(request, pk):
    """Retourne l'état des places en temps réel (public, aucune auth requise)."""
    ws = get_object_or_404(Workshop, pk=pk)
    return JsonResponse({
        'id':         ws.pk,
        'title':      ws.title,
        'capacity':   ws.capacity,
        'confirmed':  ws.confirmed_count,
        'seats_left': ws.seats_left,
        'waitlist':   ws.waitlist_count,
        'is_open':    ws.is_open,
        'fill_rate':  ws.fill_rate,
        'has_started': ws.has_started,
        'booking_closed_reason': ws.booking_closed_reason,
    })


@login_required
@require_POST
def api_generate_description(request):
    """
    Génère une description d'atelier via Ollama (llama3.2).
    Body JSON : {title, tags, speaker, level}
    Retourne : {description, ok, error?}
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    title = payload.get('title', '').strip()
    tags = payload.get('tags', [])
    speaker = payload.get('speaker', '').strip()
    level = payload.get('level', 'Débutant')

    if not title:
        return JsonResponse({'ok': False, 'error': 'Le titre est requis.'}, status=400)

    from .services.ollama_ai import generate_workshop_description, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    description = generate_workshop_description(title, tags, speaker, level)
    return JsonResponse({'ok': True, 'description': description})
