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
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Booking, Workshop, WorkshopQuiz

logger = logging.getLogger(__name__)


def _is_organizer(user):
    return getattr(user, 'role', None) in ('admin', 'mentor')


def _can_manage(user, workshop):
    if getattr(user, 'role', None) == 'admin':
        return True
    return (
        getattr(user, 'role', None) == 'mentor'
        and workshop.created_by_id == user.pk
    )


def _forbidden():
    return JsonResponse(
        {'ok': False, 'error': 'Action réservée aux organisateurs.'},
        status=403,
    )


def _parse_json_body(request):
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


@login_required
@require_GET
def api_recommend(request):
    """Retourne les recommandations IA pour l'utilisateur courant (JSON)."""
    try:
        from .services.recommend import recommend
        now = timezone.now()
        workshops = list(
            Workshop.objects.filter(is_open=True, ends_at__gte=now)
            .exclude(Q(mode__in=['onsite', 'online']) & Q(starts_at__lt=now))
            .select_related('created_by')
            .order_by('starts_at')
        )
        booked_ids = set(
            Booking.objects.filter(
                user=request.user,
                status__in=['confirmed', 'waiting', 'attended'],
            ).values_list('workshop_id', flat=True)
        )
        recommended = [
            w for w in recommend(request.user, workshops, top_n=6)
            if getattr(w, 'ai_score', 0) > 0 and w.pk not in booked_ids
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
    if not _is_organizer(request.user):
        return _forbidden()

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


@login_required
@require_POST
def api_generate_titles(request):
    """
    Génère 3 titres d'atelier via Ollama.
    Body JSON : {theme, audience, level}
    Retourne : {titles: [...], ok, error?}
    """
    if not _is_organizer(request.user):
        return _forbidden()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    theme = payload.get('theme', '').strip()
    audience = payload.get('audience', '').strip()
    level = payload.get('level', 'Débutant')

    if not theme:
        return JsonResponse({'ok': False, 'error': 'Le thème est requis.'}, status=400)

    from .services.ollama_ai import generate_workshop_titles, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    titles = generate_workshop_titles(theme, audience, level)
    return JsonResponse({'ok': True, 'titles': titles})


@login_required
@require_POST
def api_generate_objectives(request):
    """
    Génère des objectifs pédagogiques via Ollama.
    Body JSON : {title, level, tags}
    Retourne : {objectives: [...], ok, error?}
    """
    if not _is_organizer(request.user):
        return _forbidden()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    title = payload.get('title', '').strip()
    level = payload.get('level', 'Débutant')
    tags = payload.get('tags', [])

    if not title:
        return JsonResponse({'ok': False, 'error': 'Le titre est requis.'}, status=400)

    from .services.ollama_ai import generate_pedagogical_objectives, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    objectives = generate_pedagogical_objectives(title, level, tags)
    return JsonResponse({'ok': True, 'objectives': objectives})


@login_required
@require_POST
def api_generate_summary(request):
    """
    Génère un résumé court d'atelier via Ollama.
    Body JSON : {title, description, level}
    Retourne : {summary, ok, error?}
    """
    if not _is_organizer(request.user):
        return _forbidden()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    title = payload.get('title', '').strip()
    description = payload.get('description', '').strip()
    level = payload.get('level', 'Débutant')

    if not title:
        return JsonResponse({'ok': False, 'error': 'Le titre est requis.'}, status=400)

    from .services.ollama_ai import generate_workshop_summary, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    summary = generate_workshop_summary(title, description, level)
    return JsonResponse({'ok': True, 'summary': summary})


@login_required
@require_POST
def api_explain_recommendation(request):
    """
    Génère une explication personnalisée de recommandation via Ollama.
    Body JSON : {workshop_title, matched_terms, user_profile}
    Retourne : {explanation, ok, error?}
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    workshop_title = payload.get('workshop_title', '').strip()
    matched_terms = payload.get('matched_terms', [])
    user_profile = payload.get('user_profile', '').strip()

    if not workshop_title:
        return JsonResponse({'ok': False, 'error': 'Le titre de l\'atelier est requis.'}, status=400)

    from .services.ollama_ai import explain_recommendation, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    explanation = explain_recommendation(workshop_title, matched_terms, user_profile)
    return JsonResponse({'ok': True, 'explanation': explanation})


@login_required
@require_POST
def api_generate_quiz(request, pk):
    """
    Génère un quiz de compréhension pour un atelier enregistré via Ollama.
    Body JSON : {num_questions}
    Retourne : {questions: [...], ok, error?}
    """
    ws = get_object_or_404(Workshop, pk=pk)

    if not _can_manage(request.user, ws):
        return _forbidden()

    if ws.mode != Workshop.Mode.RECORDED:
        return JsonResponse({'ok': False, 'error': 'Le quiz est uniquement disponible pour les ateliers en mode replay.'}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    try:
        num_questions = int(payload.get('num_questions', 5))
    except (TypeError, ValueError):
        num_questions = 5
    num_questions = max(1, min(20, num_questions))

    from .services.ollama_ai import generate_quiz_questions, is_ollama_available

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    questions = generate_quiz_questions(
        ws.title,
        ws.description or '',
        ws.level,
        num_questions,
        tags=ws.topic_tags if isinstance(ws.topic_tags, list) else None,
    )
    return JsonResponse({'ok': True, 'questions': questions})


@login_required
@require_POST
def api_suggest_quiz_options(request, pk):
    """
    Propose 4 options + la bonne réponse pour une question saisie par
    l'organisateur, à partir du contenu de l'atelier.
    Body JSON : {question}
    Retourne : {ok, options, correct_index, explanation, error?}
    """
    ws = get_object_or_404(Workshop, pk=pk)

    if not _can_manage(request.user, ws):
        return _forbidden()

    if ws.mode != Workshop.Mode.RECORDED:
        return JsonResponse({'ok': False, 'error': 'Le quiz est uniquement disponible pour les ateliers en mode replay.'}, status=400)

    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    question = str(payload.get('question', '')).strip()
    if not question:
        return JsonResponse({'ok': False, 'error': 'La question est requise.'}, status=400)

    from .services.ollama_ai import is_ollama_available, suggest_quiz_options

    if not is_ollama_available():
        return JsonResponse({
            'ok': False,
            'error': 'Ollama est indisponible ou le modèle llama3.2 n\'est pas chargé.',
        }, status=503)

    suggestion = suggest_quiz_options(
        question, ws.title, ws.description or '', ws.level)
    if not suggestion:
        return JsonResponse({
            'ok': False,
            'error': 'L\'IA n\'a pas pu proposer d\'options. Réessayez ou saisissez-les manuellement.',
        }, status=502)

    return JsonResponse({'ok': True, **suggestion})


@login_required
@require_POST
def api_save_quiz_questions(request, pk):
    """
    Enregistre en une fois plusieurs questions générées par l'IA.
    Body JSON : {questions: [{question, options, correct_index, explanation}, ...]}
    Retourne : {ok, created, skipped}
    """
    ws = get_object_or_404(Workshop, pk=pk)

    if not _can_manage(request.user, ws):
        return _forbidden()

    if ws.mode != Workshop.Mode.RECORDED:
        return JsonResponse({'ok': False, 'error': 'Le quiz est uniquement disponible pour les ateliers en mode replay.'}, status=400)

    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)

    questions = payload.get('questions')
    if not isinstance(questions, list) or not questions:
        return JsonResponse({'ok': False, 'error': 'Aucune question à enregistrer.'}, status=400)

    created = 0
    skipped = 0
    with transaction.atomic():
        for item in questions[:30]:
            if not isinstance(item, dict):
                skipped += 1
                continue

            question = str(item.get('question', '')).strip()
            options = item.get('options')
            if not isinstance(options, (list, tuple)):
                options = [
                    item.get('option_a'), item.get('option_b'),
                    item.get('option_c'), item.get('option_d'),
                ]
            options = [str(option).strip() for option in options if option is not None]
            if not question or len(options) != 4 or not all(options):
                skipped += 1
                continue

            try:
                correct_index = int(item.get('correct_index', 0))
            except (TypeError, ValueError):
                correct_index = 0
            correct_index = min(3, max(0, correct_index))

            WorkshopQuiz.objects.create(
                workshop=ws,
                question=question,
                option_a=options[0],
                option_b=options[1],
                option_c=options[2],
                option_d=options[3],
                correct_index=correct_index,
                explanation=str(item.get('explanation', '')).strip(),
                created_by=request.user,
            )
            created += 1

    if created:
        return JsonResponse({'ok': True, 'created': created, 'skipped': skipped})
    return JsonResponse({
        'ok': False,
        'error': 'Aucune question valide : 4 options et un intitulé sont requis.',
        'skipped': skipped,
    }, status=400)
