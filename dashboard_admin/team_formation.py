"""Weighted, explainable recommendations for balancing unassigned students."""

import re
import unicodedata

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef

from student.models import Hackathon, HackathonRegistration, Team, TeamMembership


ROLE_LABELS = {
    'developer': 'Développement', 'designer': 'Design / UX', 'business': 'Business / Pitch',
    'product': 'Produit', 'data_ai': 'Data / IA',
}
ROLE_TERMS = {
    'developer': {'developer', 'development', 'developpeur', 'developpement', 'backend', 'frontend', 'fullstack', 'programming', 'python', 'django', 'react', 'javascript', 'typescript', 'java', 'api', 'devops'},
    'designer': {'designer', 'design', 'ux', 'ui', 'figma', 'prototype', 'prototyping', 'maquette', 'graphisme'},
    'business': {'business', 'pitch', 'marketing', 'finance', 'sales', 'vente', 'entrepreneur', 'commercial', 'budget'},
    'product': {'product', 'produit', 'productowner', 'research', 'recherche', 'userresearch', 'strategy', 'strategie'},
    'data_ai': {'data', 'ai', 'ia', 'machinelearning', 'ml', 'analytics', 'analyse', 'pytorch', 'tensorflow'},
}


def _normal(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9+#]+', ' ', value).strip()


def _skills(user):
    return {normalized for skill in (user.skills if isinstance(user.skills, list) else []) if (normalized := _normal(skill))}


def _roles(user):
    explicit = set(user.preferred_roles or [])
    profile_text = _normal(' '.join([user.specialty or '', *[str(value) for value in (user.skills if isinstance(user.skills, list) else [])]]))
    profile_words = set(profile_text.split())
    profile_joined = profile_text.replace(' ', '')
    detected = {role for role, terms in ROLE_TERMS.items() if profile_words & terms or any(term in profile_joined for term in terms if len(term) > 5)}
    return detected, explicit


def _availability(user):
    values = user.availability_windows if isinstance(user.availability_windows, list) else []
    return {value for value in values if value in {'weekday_day', 'weekday_evening', 'weekend', 'flexible'}}


def _team_context(team):
    members = [membership.user for membership in team.memberships.select_related('user').all()]
    return {
        'team': team,
        'members': members,
        'skills': set().union(*(_skills(member) for member in members)) if members else set(),
        'availability': [_availability(member) for member in members if _availability(member)],
        'planned': [],
    }


def _requested_skills(team):
    return [term.strip() for term in re.split(r'[,;/|]', team.seeking_skill or '') if term.strip()]


def _skill_match(term, skills):
    wanted = _normal(term)
    return any(wanted == skill or wanted in skill or skill in wanted for skill in skills if len(skill) > 2)


def _category_fit(student, team):
    preferences = [_normal(item) for item in (student.preferred_categories or '').split(',') if _normal(item)]
    if not preferences:
        return 0.5
    corpus = _normal(' '.join([team.category, team.project_name, team.description, team.project_pitch]))
    corpus_words = set(corpus.split())
    scores = []
    for preference in preferences:
        if preference in corpus:
            scores.append(1.0)
        else:
            words = set(preference.split())
            scores.append(len(words & corpus_words) / max(len(words), 1))
    return max(scores, default=0.0)


def _preference_fit(student, context):
    team, members = context['team'], context['members'] + context['planned']
    desired_roles = set(student.preferred_roles or [])
    if desired_roles:
        gaps = [1.0 if not any(role in _roles(member)[0] for member in members) else 0.3 for role in desired_roles]
        role_fit = sum(gaps) / len(gaps)
    else:
        role_fit = 0.5
    category_fit = _category_fit(student, team)
    weights = (int(bool(desired_roles)), int(bool((student.preferred_categories or '').strip())))
    if not any(weights):
        return 0.5
    return (role_fit * weights[0] + category_fit * weights[1]) / sum(weights)


def _availability_fit(student, context):
    candidate = _availability(student)
    team_availability = context['availability'] + [
        windows for windows in (_availability(member) for member in context['planned']) if windows
    ]
    if not candidate or not team_availability:
        return 0.5
    if 'flexible' in candidate:
        return 1.0
    common = set(candidate)
    for member_windows in team_availability:
        if 'flexible' not in member_windows:
            common &= member_windows
    return len(common) / len(candidate)


def _score(student, context):
    team = context['team']
    current_members = context['members'] + context['planned']
    student_skills = _skills(student)
    team_skills = context['skills'] | set().union(*(_skills(member) for member in context['planned'])) if context['planned'] else context['skills']
    requirements = _requested_skills(team)
    missing_before = [item for item in requirements if not _skill_match(item, team_skills)]
    if missing_before:
        skill_fit = sum(_skill_match(item, student_skills) for item in missing_before) / len(missing_before)
    elif requirements:
        skill_fit = 0.15
    else:
        new_skill_count = len(student_skills - team_skills)
        skill_fit = min(1.0, new_skill_count / 3) if student_skills else 0.4

    roles, _ = _roles(student)
    if roles:
        role_fit = sum(1 / (1 + sum(role in _roles(member)[0] for member in current_members)) for role in roles) / len(roles)
    else:
        role_fit = 0.45
    preference_fit = _preference_fit(student, context)
    availability_fit = _availability_fit(student, context)
    load_fit = 1 - (len(current_members) / max(team.max_members, 1))
    score = round(100 * (0.40 * skill_fit + 0.25 * role_fit + 0.20 * preference_fit + 0.10 * availability_fit + 0.05 * load_fit))

    reasons = []
    covered = [item for item in missing_before if _skill_match(item, student_skills)]
    if covered:
        reasons.append('Comble le besoin en compétences : ' + ', '.join(covered[:3]))
    elif student_skills - team_skills:
        reasons.append('Ajoute des compétences absentes de l’équipe')
    complementary_roles = [ROLE_LABELS[role] for role in roles if not any(role in _roles(member)[0] for member in current_members)]
    if complementary_roles:
        reasons.append('Apporte un rôle complémentaire : ' + ', '.join(complementary_roles))
    if (student.preferred_categories or '').strip() and _category_fit(student, team) > 0:
        reasons.append('Projet proche de ses thématiques préférées')
    if student.preferred_roles:
        reasons.append('Respecte ses rôles préférés autant que la composition le permet')
    team_availability = context['availability'] + [
        windows for windows in (_availability(member) for member in context['planned']) if windows
    ]
    if _availability(student) and team_availability:
        if availability_fit >= 0.5:
            reasons.append('Disponibilités compatibles avec les membres renseignés')
        else:
            reasons.append('Disponibilités moins compatibles avec l’équipe')
    reasons.append(f'Équipe à {len(current_members)}/{team.max_members} membres avant affectation')
    return score, reasons


def generate_team_plan():
    """Greedily allocate the most constrained profiles to the best balanced open team."""
    hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    teams = list((Team.objects.filter(hackathon=hackathon) if hackathon else Team.objects.all()).order_by('name'))
    contexts = [_team_context(team) for team in teams]
    User = get_user_model()
    student_pool = User.objects.filter(role='student', is_active=True)
    if hackathon:
        registered_ids = HackathonRegistration.objects.filter(hackathon=hackathon).values('user_id')
        student_pool = student_pool.filter(pk__in=registered_ids)
    unassigned = list(student_pool.annotate(
        has_team=Exists(TeamMembership.objects.filter(user_id=OuterRef('pk'))),
    ).filter(has_team=False).order_by('pk'))
    unassigned.sort(key=lambda student: (
        bool(student.preferred_roles) + bool(student.preferred_categories) + bool(student.availability_windows),
        len(student.skills if isinstance(student.skills, list) else []),
    ), reverse=True)

    assignments = []
    for student in unassigned:
        available = [context for context in contexts if len(context['members']) + len(context['planned']) < context['team'].max_members]
        if not available:
            break
        choices = [(_score(student, context), context) for context in available]
        (score, reasons), selected = max(choices, key=lambda pair: (pair[0][0], -len(pair[1]['members']) - len(pair[1]['planned']), pair[1]['team'].name.casefold()))
        selected['planned'].append(student)
        assignments.append({'student_id': student.pk, 'team_id': selected['team'].pk, 'score': score, 'reasons': reasons})

    recommendations = []
    for context in contexts:
        after_members = context['members'] + context['planned']
        all_skills = set().union(*(_skills(member) for member in after_members)) if after_members else set()
        missing_skills = [item for item in _requested_skills(context['team']) if not _skill_match(item, all_skills)]
        present_roles = set().union(*(_roles(member)[0] for member in after_members)) if after_members else set()
        missing_roles = [ROLE_LABELS[role] for role in ('developer', 'designer', 'business') if role not in present_roles] if context['team'].max_members >= 3 else []
        additions = [
            {
                'student_id': assignment['student_id'], 'name': (student.get_full_name() or student.username),
                'score': assignment['score'], 'reasons': assignment['reasons'],
            }
            for assignment in assignments if assignment['team_id'] == context['team'].pk
            for student in [next(user for user in context['planned'] if user.pk == assignment['student_id'])]
        ]
        recommendations.append({
            'team_id': context['team'].pk, 'team_name': context['team'].name,
            'current_count': len(context['members']), 'recommended_count': len(after_members),
            'max_members': context['team'].max_members, 'full': len(after_members) >= context['team'].max_members,
            'additions': additions,
            'missing_skills': missing_skills, 'missing_roles': missing_roles,
        })

    remaining = len(unassigned) - len(assignments)
    remaining_students = [
        {'id': student.pk, 'name': student.get_full_name() or student.username}
        for student in unassigned[len(assignments):]
    ]
    return {
        'hackathon_id': hackathon.pk if hackathon else None,
        'hackathon_name': hackathon.name if hackathon else 'Toutes les équipes',
        'assignments': assignments,
        'recommendations': recommendations,
        'unassigned_count': len(unassigned),
        'remaining_count': remaining,
        'remaining_students': remaining_students,
    }
