"""Services IA du module Hackathons : classement local, création/exécution des tâches, cache et quotas."""
import hashlib
import json
import logging
import os
import re
from datetime import timedelta

from django.utils import timezone

from . import ai_prompts as prompts
from . import gemini
from .models import AIJob, Challenge, HackathonProfile

logger = logging.getLogger(__name__)

CACHE_HOURS = 24
ADMIN_ROLES = ('admin', 'organization')

FEATURES = {
    AIJob.Feature.HACKATHON_DRAFT: {
        'roles': ADMIN_ROLES, 'prompt': prompts.hackathon_draft_prompt,
        'validator': lambda payload: prompts.hackathon_draft_validate, 'temperature': 0.8,
    },
    AIJob.Feature.CHALLENGE_DRAFT: {
        'roles': ADMIN_ROLES, 'prompt': prompts.challenge_draft_prompt,
        'validator': lambda payload: prompts.challenge_draft_validate, 'temperature': 0.8,
    },
    AIJob.Feature.STUDENT_COACH: {
        'roles': ('student',), 'prompt': prompts.student_coach_prompt,
        'validator': lambda payload: prompts.student_coach_validate, 'temperature': 0.5,
    },
    AIJob.Feature.STUDENT_RECOMMEND: {
        'roles': ('student',), 'prompt': prompts.student_recommend_prompt,
        'validator': lambda payload: prompts.student_recommend_validator(
            {c['id'] for c in payload.get('challenges', [])}, {h['id'] for h in payload.get('hackathons', [])}),
        'temperature': 0.4,
    },
    AIJob.Feature.MENTOR_EXPLAIN: {
        'roles': ('mentor',), 'prompt': prompts.mentor_explain_prompt,
        'validator': lambda payload: prompts.mentor_explain_validate, 'temperature': 0.5,
    },
}


class AIRejected(Exception):
    """Demande refusée avant l'appel IA (quota, rôle…) ; le message est affichable."""


# ------------------------------------------------------------ Classement local

SKILL_KEYWORDS = {
    'python / django': ['python', 'django', 'flask', 'backend', 'api rest', 'orm'],
    'react / typescript': ['react', 'typescript', 'javascript', 'frontend', 'front-end', 'next.js', 'web'],
    'vue.js': ['vue', 'nuxt', 'frontend', 'front-end'],
    'fastapi': ['fastapi', 'python', 'api', 'backend', 'microservice'],
    'ui/ux & figma': ['ui', 'ux', 'figma', 'design', 'interface', 'prototype', 'maquette', 'expérience utilisateur'],
    'ia & machine learning': ['ia', 'ai', 'intelligence artificielle', 'machine learning', 'ml', 'nlp', 'tensorflow',
                              'pytorch', 'modèle', 'vision', 'recommandation', 'data'],
    'devops & docker': ['docker', 'devops', 'ci/cd', 'kubernetes', 'cloud', 'déploiement', 'deploiement', 'pipeline',
                        'infrastructure'],
    'flutter / mobile': ['flutter', 'dart', 'mobile', 'android', 'ios', 'react native'],
    'postgresql': ['postgresql', 'postgres', 'sql', 'base de données', 'database', 'données'],
    'pitch & business model': ['pitch', 'business', 'modèle économique', 'startup', 'marketing', 'présentation',
                               'impact', 'commercial'],
}


def _contains(keyword, text):
    return bool(re.search(r'(?<![\w])' + re.escape(keyword) + r'(?![\w])', text))


def _keywords_for(skill):
    key = skill.strip().lower()
    if key in SKILL_KEYWORDS:
        return SKILL_KEYWORDS[key]
    return [key] + [token for token in re.findall(r'[\w+#.]+', key) if len(token) >= 3]


def student_skills(user):
    skills = [str(s).strip() for s in (user.skills or []) if str(s).strip()]
    specialty = (user.specialty or '').strip()
    if specialty and specialty.casefold() not in {s.casefold() for s in skills}:
        skills.append(specialty)
    return skills


def score_challenge(challenge, skills):
    technologies = challenge.technologies.lower()
    title = f'{challenge.title} {challenge.short_description}'.lower()
    body = ' '.join([
        challenge.description, challenge.objectives, challenge.problem_statement, challenge.deliverables,
        challenge.constraints, challenge.hackathon.track.name, challenge.hackathon.title,
        challenge.hackathon.short_description,
    ]).lower()
    total, matched = 0.0, []
    for skill in skills:
        best, hits = 0.0, 0
        for keyword in _keywords_for(skill):
            keyword = keyword.lower()
            level = 3.0 if _contains(keyword, technologies) else 2.0 if _contains(keyword, title) \
                else 1.0 if _contains(keyword, body) else 0.0
            if level:
                hits += 1
                best = max(best, level)
        if best:
            total += min(3.0, best + 0.5 * (hits - 1))
            matched.append(skill)
    denominator = 3.0 * max(1, min(len(skills), 4))
    return min(100, round(100 * total / denominator)), matched


def rank_published(user):
    """Classe défis et hackathons publiés selon les compétences de l'étudiant (score local, sans appel IA)."""
    skills = student_skills(user)
    challenges = Challenge.objects.filter(
        status=Challenge.Status.PUBLISHED, hackathon__status=HackathonProfile.Status.PUBLISHED,
    ).select_related('hackathon', 'hackathon__event', 'hackathon__track')
    ranked = []
    for challenge in challenges:
        score, matched = score_challenge(challenge, skills)
        ranked.append({'challenge': challenge, 'score': score, 'matched': matched})
    ranked.sort(key=lambda item: (-item['score'], item['challenge'].title.casefold()))

    hackathons = {}
    for item in ranked:
        h = item['challenge'].hackathon
        entry = hackathons.setdefault(h.pk, {'hackathon': h, 'score': 0, 'matched': [], 'challenge_count': 0})
        entry['challenge_count'] += 1
        if item['score'] > entry['score']:
            entry['score'], entry['matched'] = item['score'], item['matched']
    ranked_hackathons = sorted(hackathons.values(), key=lambda e: (-e['score'], e['hackathon'].title.casefold()))
    return skills, ranked, ranked_hackathons


# ------------------------------------------------------------------ Contextes

def profile_context(user):
    return {
        'competences': student_skills(user), 'niveau_etudes': prompts.clip(user.study_level, 80),
        'roles_preferes': [prompts.clip(r, 60) for r in (user.preferred_roles or [])][:6],
        'themes_preferes': prompts.clip(user.preferred_categories, 200), 'bio': prompts.clip(user.bio, 300),
    }


def challenge_context(challenge):
    h = challenge.hackathon
    return {
        'id': challenge.pk, 'titre': challenge.title, 'hackathon': h.title, 'track': h.track.name,
        'difficulte': challenge.get_difficulty_display(),
        'resume': prompts.clip(challenge.short_description, 240),
        'description': prompts.clip(challenge.description, 1500), 'objectifs': prompts.clip(challenge.objectives, 800),
        'problematique': prompts.clip(challenge.problem_statement, 800), 'contraintes': prompts.clip(challenge.constraints, 600),
        'livrables': prompts.clip(challenge.deliverables, 600), 'technologies': challenge.technology_list[:10],
    }


def hackathon_context(h):
    return {
        'id': h.pk, 'titre': h.title, 'track': h.track.name, 'resume': prompts.clip(h.short_description, 240),
        'description': prompts.clip(h.description, 1500), 'reglement': prompts.clip(h.rules, 800),
        'challenges': [
            {'titre': c.title, 'difficulte': c.get_difficulty_display(), 'technologies': c.technology_list[:8]}
            for c in h.published_challenges[:12]
        ],
    }


# --------------------------------------------------------------- Tâches IA

def payload_hash(feature, payload):
    raw = json.dumps({'f': feature, 'p': payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _rate_limit():
    try:
        return max(1, int(os.environ.get('HACKATHONS_AI_REQUESTS_PER_HOUR', '30')))
    except ValueError:
        return 30


def create_job(user, feature, payload, refresh=False):
    spec = FEATURES.get(feature)
    if spec is None or user.role not in spec['roles']:
        raise AIRejected('Cette fonctionnalité IA n’est pas disponible pour votre rôle.')
    digest = payload_hash(feature, payload)

    if not refresh:
        since = timezone.now() - timedelta(hours=CACHE_HOURS)
        hit = AIJob.objects.filter(
            feature=feature, payload_hash=digest, status=AIJob.Status.DONE, created_at__gte=since,
        ).order_by('-created_at').first()
        if hit:
            return AIJob.objects.create(
                user=user, feature=feature, payload=payload, payload_hash=digest, status=AIJob.Status.DONE,
                result=hit.result, model_used=hit.model_used, cached=True, latency_ms=0,
                input_chars=hit.input_chars, output_chars=hit.output_chars, finished_at=timezone.now(),
            )

    recent = AIJob.objects.filter(
        user=user, cached=False, created_at__gte=timezone.now() - timedelta(hours=1)).count()
    if recent >= _rate_limit():
        raise AIRejected('Vous avez atteint la limite de requêtes IA pour cette heure. Réessayez plus tard.')
    return AIJob.objects.create(user=user, feature=feature, payload=payload, payload_hash=digest)


def run_job(job_id):
    """Exécutée par Celery : appelle Gemini (modèle principal puis secours) et enregistre résultat et mesures."""
    job = AIJob.objects.filter(pk=job_id).first()
    if job is None or job.status != AIJob.Status.PENDING:
        return
    now = timezone.now()
    job.status = AIJob.Status.RUNNING
    job.queue_ms = max(0, round((now - job.created_at).total_seconds() * 1000))
    job.save(update_fields=['status', 'queue_ms'])

    spec = FEATURES[job.feature]
    result, error, meta = {}, '', {}
    try:
        prompt = spec['prompt'](job.payload)
        result, meta = gemini.generate_json(prompt, spec['validator'](job.payload), spec['temperature'])
    except gemini.GeminiError as exc:
        error, meta = str(exc), exc.meta
    except Exception:
        logger.exception('Erreur inattendue pendant la tâche IA %s', job_id)
        error = 'Une erreur inattendue est survenue. Réessayez dans un instant.'

    job.status = AIJob.Status.FAILED if error else AIJob.Status.DONE
    job.result = result
    job.error_message = error[:400]
    job.model_used = meta.get('model', '')
    job.fallback_used = bool(meta.get('fallback_used'))
    job.primary_error = meta.get('primary_error', '')[:300]
    job.latency_ms = meta.get('latency_ms', 0)
    job.input_chars = meta.get('input_chars', 0)
    job.output_chars = meta.get('output_chars', 0)
    job.finished_at = timezone.now()
    job.save()
