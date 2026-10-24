"""Draft announcement and email copy with local Ollama, grounded in event data."""

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.db.models import Exists, OuterRef

from student.models import Announcement, Hackathon, Milestone, Submission, Team


class AnnouncementGenerationError(Exception):
    """Raised when Ollama cannot produce a usable announcement draft."""


AUDIENCE_TEAMS_WITHOUT_SUBMISSION = 'teams_without_submission'


def _target_context(audience):
    hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    if audience != AUDIENCE_TEAMS_WITHOUT_SUBMISSION:
        audience_label = dict(Announcement.Audience.choices).get(audience)
        if not audience_label:
            raise ValueError('Choisissez une audience valide.')
        return {'hackathon': hackathon.name if hackathon else None, 'audience': audience_label}, None

    if not hackathon:
        raise ValueError('Activez un hackathon pour cibler les équipes sans dépôt.')
    milestone = Milestone.objects.filter(hackathon=hackathon).order_by('-due_at', '-pk').first()
    if not milestone:
        raise ValueError('Aucun jalon n’est défini pour ce hackathon.')
    submitted = Submission.objects.filter(
        team_id=OuterRef('pk'), milestone=milestone,
        status__in=(Submission.Status.SUBMITTED, Submission.Status.APPROVED, Submission.Status.REVISION),
    )
    missing_teams = Team.objects.filter(hackathon=hackathon).annotate(has_submission=Exists(submitted)).filter(has_submission=False)
    target_count = missing_teams.count()
    teams = list(missing_teams.order_by('name')[:100])
    target = {
        'hackathon': hackathon.name,
        'audience': 'Équipes sans dépôt pour le jalon « %s »' % milestone.title,
        'jalon': milestone.title,
        'deadline': milestone.due_at.strftime('%d/%m/%Y %H:%M') if milestone.due_at else None,
        'equipes_ciblees': [team.name for team in teams],
        'nombre_equipes': target_count,
        'limite_liste': 100,
    }
    return target, {'milestone': milestone, 'teams': teams}


def generate_announcement_draft(*, audience, topic, tone, message_type):
    """Generate a draft. This function never publishes or sends it."""
    topic = topic.strip()[:500]
    if not topic:
        raise ValueError('Indiquez le sujet ou les informations à communiquer.')
    if tone not in {'professionnel', 'chaleureux', 'direct', 'enthousiaste'}:
        raise ValueError('Choisissez un ton valide.')
    if message_type not in {'annonce', 'rappel', 'email'}:
        raise ValueError('Choisissez un format valide.')

    target, targeting = _target_context(audience)
    system = (
        'Tu rédiges un brouillon en français pour un organisateur de hackathon. '
        'Utilise uniquement les informations présentes dans le JSON fourni; n’invente ni dates, ni liens, ni consignes. '
        'Reste concis, adapte le ton et le format. Si une information manque, laisse un espace explicite entre crochets. '
        'Pour la cible teams_without_submission, le corps doit s’adresser à {{team_name}} et être personnalisable équipe par équipe. '
        'Ne prétends jamais que le message a été envoyé ou publié. Retourne uniquement le JSON demandé.'
    )
    schema = {
        'type': 'object',
        'properties': {'title': {'type': 'string'}, 'body': {'type': 'string'}},
        'required': ['title', 'body'], 'additionalProperties': False,
    }
    request_data = {
        'model': getattr(settings, 'OLLAMA_COPILOT_MODEL', 'qwen2.5:7b'),
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps({
                'format': message_type, 'ton': tone, 'sujet_et_consignes': topic,
                'evenement_et_cible': target,
            }, ensure_ascii=False)},
        ],
        'stream': False, 'format': schema, 'options': {'temperature': 0.35},
    }
    base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    request = urllib.request.Request(
        f'{base_url}/api/chat', data=json.dumps(request_data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
        draft = json.loads(result.get('message', {}).get('content', ''))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        raise AnnouncementGenerationError('Ollama ne répond pas ou a renvoyé un brouillon invalide. Vérifiez le serveur et le modèle local.') from exc
    title = str(draft.get('title', '')).strip()[:220] if isinstance(draft, dict) else ''
    body = str(draft.get('body', '')).strip()[:5000] if isinstance(draft, dict) else ''
    if not title or not body:
        raise AnnouncementGenerationError('Ollama a renvoyé un brouillon incomplet. Réessayez avec un sujet plus précis.')

    return {
        'title': title, 'body': body, 'audience': audience,
        'is_targeted_email': targeting is not None,
        'target_team_count': target['nombre_equipes'] if targeting else None,
        'target_teams': [team.name for team in targeting['teams']] if targeting else [],
        'target_label': target['audience'],
        'milestone': target.get('jalon'),
        'deadline': target.get('deadline'),
    }
