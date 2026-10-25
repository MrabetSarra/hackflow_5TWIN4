"""Vues de l'assistant IA (Gemini) : démarrage asynchrone, suivi, retours et pages étudiant/mentor."""
import logging

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import role_required

from . import ai_services as services
from . import images
from .ai_prompts import clip
from .models import AIJob, Challenge, HackathonProfile, Registration
from .views import page

try:
    from kombu.exceptions import OperationalError as CeleryOperationalError
except ImportError:
    class CeleryOperationalError(Exception):
        pass

logger = logging.getLogger(__name__)

PUBLISHED = HackathonProfile.Status.PUBLISHED
RECOMMENDATION_LIMIT = 8
BANNER_REQUESTS_PER_HOUR = 10


# ------------------------------------------------------------ Construction des charges utiles

def _bad(message):
    raise services.AIRejected(message)


def _published_challenge(raw_id):
    if not str(raw_id).isdigit():
        _bad('Challenge introuvable.')
    return get_object_or_404(
        Challenge.objects.select_related('hackathon', 'hackathon__track'),
        pk=int(raw_id), status=Challenge.Status.PUBLISHED, hackathon__status=PUBLISHED,
    )


def _payload_hackathon_draft(request):
    title = clip(request.POST.get('title'), 160)
    if len(title) < 3:
        _bad('Saisissez d’abord un titre d’au moins 3 caractères.')
    return {'titre': title, 'track': clip(request.POST.get('track'), 120), 'consignes': clip(request.POST.get('instructions'), 400)}


def _payload_challenge_draft(request):
    title = clip(request.POST.get('title'), 160)
    if len(title) < 3:
        _bad('Saisissez d’abord un titre d’au moins 3 caractères.')
    raw = request.POST.get('hackathon_id', '')
    hackathon = get_object_or_404(HackathonProfile.objects.select_related('track'), pk=int(raw)) if raw.isdigit() else _bad(
        'Hackathon introuvable.')
    return {
        'titre': title, 'hackathon': hackathon.title, 'track': hackathon.track.name,
        'resume_hackathon': clip(hackathon.short_description or hackathon.description, 400),
        'consignes': clip(request.POST.get('instructions'), 400),
    }


def _payload_student_coach(request):
    challenge = _published_challenge(request.POST.get('challenge_id'))
    skills = services.student_skills(request.user)
    score, matched = services.score_challenge(challenge, skills)
    return {
        'defi': services.challenge_context(challenge), 'profil': services.profile_context(request.user),
        'score_local': score, 'competences_correspondantes': matched,
    }


def _payload_student_recommend(request):
    skills, ranked, ranked_hackathons = services.rank_published(request.user)
    if not skills:
        _bad('Ajoutez vos compétences dans votre profil pour obtenir des recommandations personnalisées.')
    if not ranked:
        _bad('Aucun challenge publié pour le moment.')
    return {
        'profil': services.profile_context(request.user),
        'challenges': [
            {**services.challenge_context(item['challenge']), 'local_score': item['score'], 'matched': item['matched']}
            for item in ranked[:RECOMMENDATION_LIMIT]
        ],
        'hackathons': [
            {'id': e['hackathon'].pk, 'titre': e['hackathon'].title, 'track': e['hackathon'].track.name,
             'local_score': e['score']}
            for e in ranked_hackathons[:4]
        ],
    }


def _payload_mentor_explain(request):
    kind = request.POST.get('kind', '')
    if kind == 'challenge':
        return {'type': 'challenge', 'element': services.challenge_context(_published_challenge(request.POST.get('id')))}
    if kind == 'hackathon' and request.POST.get('id', '').isdigit():
        hackathon = get_object_or_404(
            HackathonProfile.objects.select_related('track'), pk=int(request.POST['id']), status=PUBLISHED)
        return {'type': 'hackathon', 'element': services.hackathon_context(hackathon)}
    _bad('Élément à expliquer introuvable.')


PAYLOAD_BUILDERS = {
    AIJob.Feature.HACKATHON_DRAFT: _payload_hackathon_draft,
    AIJob.Feature.CHALLENGE_DRAFT: _payload_challenge_draft,
    AIJob.Feature.STUDENT_COACH: _payload_student_coach,
    AIJob.Feature.STUDENT_RECOMMEND: _payload_student_recommend,
    AIJob.Feature.MENTOR_EXPLAIN: _payload_mentor_explain,
}


# ------------------------------------------------------------------- Endpoints JSON

def enqueue_job(job):
    """Délègue l'appel Gemini à Celery ; en cas de broker indisponible, la tâche est marquée en échec."""
    from .tasks import run_ai_job
    try:
        run_ai_job.delay(job.pk)
    except (CeleryOperationalError, OSError, ConnectionError, TimeoutError, RuntimeError):
        logger.warning('Impossible de mettre en file la tâche IA %s', job.pk)
        job.status = AIJob.Status.FAILED
        job.error_message = 'Le service de tâches en arrière-plan est indisponible. Réessayez plus tard.'
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'finished_at'])


def job_json(job):
    data = {
        'job_id': job.pk, 'status': job.status, 'cached': job.cached, 'model': job.model_used,
        'fallback_used': job.fallback_used, 'latency_ms': job.latency_ms,
    }
    if job.status == AIJob.Status.DONE:
        data['result'] = job.result
    elif job.status == AIJob.Status.FAILED:
        data['error'] = job.error_message or 'La requête IA a échoué.'
    return data


@login_required
@require_POST
def ai_start(request, feature):
    builder = PAYLOAD_BUILDERS.get(feature)
    spec = services.FEATURES.get(feature)
    if builder is None or spec is None:
        raise Http404
    if request.user.role not in spec['roles']:
        return JsonResponse({'status': 'failed', 'error': 'Cette fonctionnalité IA n’est pas disponible pour votre rôle.'}, status=403)
    try:
        payload = builder(request)
        job = services.create_job(request.user, feature, payload, refresh=request.POST.get('refresh') == '1')
    except services.AIRejected as exc:
        return JsonResponse({'status': 'failed', 'error': str(exc)}, status=400)
    if job.status == AIJob.Status.PENDING:
        enqueue_job(job)
        job.refresh_from_db()
    return JsonResponse(job_json(job))


@login_required
@require_GET
def ai_status(request, job_id):
    job = get_object_or_404(AIJob, pk=job_id, user=request.user)
    return JsonResponse(job_json(job))


@login_required
@require_POST
def ai_feedback(request, job_id):
    job = get_object_or_404(AIJob, pk=job_id, user=request.user)
    value = request.POST.get('value')
    if value not in ('1', '-1'):
        return JsonResponse({'error': 'Valeur invalide.'}, status=400)
    job.feedback = int(value)
    job.save(update_fields=['feedback'])
    return JsonResponse({'ok': True})


# ------------------------------------------------------------------------- Pages

@role_required('student')
def ai_recommendations(request):
    skills, ranked, ranked_hackathons = services.rank_published(request.user)
    registered = set(Registration.objects.filter(
        user=request.user, status=Registration.Status.CONFIRMED).values_list('challenge_id', flat=True))
    return page(request, 'hackathons/public/ai_recommendations.html', {
        'skills': skills, 'ranked': ranked[:12], 'ranked_hackathons': ranked_hackathons[:6],
        'registered': registered, 'total_challenges': len(ranked),
    })


@role_required('mentor')
def ai_mentor(request):
    hackathons = HackathonProfile.objects.filter(status=PUBLISHED).select_related('track', 'event').prefetch_related(
        'challenges')
    for h in hackathons:
        h.public_challenges = [c for c in h.challenges.all() if c.status == Challenge.Status.PUBLISHED]
    return page(request, 'hackathons/public/ai_mentor.html', {'hackathons': hackathons})



@role_required('admin', 'organization')
@require_POST
def banner_generate(request):
    """Génère une bannière Stable Diffusion (Hugging Face) à partir du titre saisi ; retourne son aperçu."""
    title = clip(request.POST.get('title'), 160)
    if len(title) < 3:
        return JsonResponse({'error': 'Saisissez d’abord un titre d’au moins 3 caractères.'}, status=400)
    key = f'hf-banner:{request.user.pk}'
    used = cache.get(key, 0)
    if used >= BANNER_REQUESTS_PER_HOUR:
        return JsonResponse({'error': 'Limite de générations d’images atteinte pour cette heure.'}, status=429)
    prompt = images.build_prompt(
        title, clip(request.POST.get('track'), 120), clip(request.POST.get('summary'), 300),
        clip(request.POST.get('instructions'), 300))
    try:
        name = images.generate_banner(prompt)
    except images.ImageError as exc:
        return JsonResponse({'error': str(exc)}, status=502)
    cache.set(key, used + 1, 3600)
    return JsonResponse({'name': name, 'url': default_storage.url(name)})
