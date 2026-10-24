"""Deterministic, evidence-led career scoring with per-user persistent cache."""
import hashlib
import json
import re
from decimal import Decimal

from django.conf import settings

from ..models import CareerMatchCache, CareerRequirement, Opportunity, OpportunitySkill
from .cv_analysis import SKILL_ALIASES, analyze_student_cv

LEGACY_WEIGHTS = getattr(settings, 'CAREER_MATCH_WEIGHTS', {
    'skills': 40, 'education': 20, 'experience': 15, 'languages': 10, 'location': 10, 'availability': 5,
})
MIN_CONFIDENT_COVERAGE = 30


def _norm(value):
    return ' '.join(str(value or '').casefold().replace('.', ' ').replace('+', ' plus ').split())


ALIASES = {_norm(alias): _norm(canonical) for canonical, aliases in SKILL_ALIASES.items() for alias in aliases}
ALIASES.update({_norm(alias): _norm(canonical) for alias, canonical in {
    'js': 'JavaScript', 'reactjs': 'React', 'vuejs': 'Vue.js', 'postgres': 'PostgreSQL', 'k8s': 'Kubernetes',
}.items()})


def _canonical(value):
    normalized = _norm(value)
    return ALIASES.get(normalized, normalized)


def _profile_digest(user):
    payload = {'skills': user.skills or [], 'study_level': user.study_level, 'specialty': user.specialty,
               'school': user.school, 'bio': user.bio}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _evidence_for(term, values, *, aliases=False):
    target = _canonical(term) if aliases else _norm(term)
    for row in values:
        text = str(row.get('name') or row.get('text') or row.get('evidence') or '')
        key = _canonical(text) if aliases else _norm(text)
        if target and (target == key or target in key or key in target):
            evidence = row.get('evidence') or row.get('text') or text
            return str(evidence)[:500]
    return ''


def _partial_evidence(term, values):
    ignored = {'and', 'the', 'with', 'for', 'experience', 'knowledge', 'required', 'preferred', 'using'}
    target = {word for word in _norm(term).split() if word not in ignored and len(word) > 2}
    if not target:
        return ''
    for row in values:
        text = str(row.get('name') or row.get('text') or row.get('evidence') or '')
        words = set(_norm(text).split()) - ignored
        overlap = target & words
        if overlap and len(overlap) / len(target) >= .5:
            return str(row.get('evidence') or row.get('text') or text)[:500]
    return ''


def _criterion_result(*, name, kind, weight, mandatory, match, evidence, reason, suggestion=''):
    if match is None:
        status = 'not_demonstrated' if evidence == [] else 'missing_information'
        evidence_out = []
    elif match >= 85:
        status, evidence_out = 'satisfied', evidence if isinstance(evidence, list) else [evidence]
    elif match > 0:
        status, evidence_out = 'partial', evidence if isinstance(evidence, list) else [evidence]
    else:
        status, evidence_out = ('mandatory_not_met' if mandatory else 'not_demonstrated'), evidence if isinstance(evidence, list) else [evidence]
    return {'requirement': name, 'type': kind, 'weight': float(weight), 'mandatory': bool(mandatory),
            'match_pct': match, 'evidence': [item for item in evidence_out if item],
            'status': status, 'explanation': reason, 'suggestion': suggestion}


def _evaluate(name, kind, weight, mandatory, profile, profile_fields):
    skills = profile.get('skills', [])
    if kind == 'skill':
        evidence = _evidence_for(name, skills, aliases=True)
        profile_skill = next((s for s in profile_fields['skills']
                              if any(_canonical(token) == _canonical(name) for token in re.split(r'[/,&]', s))), '')
        if evidence or profile_skill:
            return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=100,
                evidence=[evidence, f'Profile skill: {profile_skill}' if profile_skill else ''], reason='The skill is explicitly listed in the CV or student profile.')
        partial = _partial_evidence(name, skills)
        if partial:
            return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=60,
                evidence=[partial], reason='Related CV evidence was found, but it does not confirm the exact named skill.',
                suggestion=f'Clarify your experience with {name} if it is relevant.')
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=None, evidence=[],
            reason='This skill is not demonstrated in the CV or profile; absence does not prove the student lacks it.',
            suggestion=f'Add {name} with a concrete example if you have this skill.')

    if kind in ('education',):
        values = profile_fields['education'] + [row.get('text', '') for row in profile.get('education', [])]
        evidence = next((value for value in values if _norm(name) in _norm(value) or _norm(value) in _norm(name)), '')
        if evidence:
            match = 100
            reason = 'The education requirement is supported by explicit profile or CV information.'
        elif values:
            degree_level = lambda value: 3 if any(word in _norm(value) for word in ('phd', 'doctorate')) else 2 if 'master' in _norm(value) else 1 if any(word in _norm(value) for word in ('bachelor', 'licence', 'license', 'but')) else 0
            required_level, current_levels = degree_level(name), [degree_level(value) for value in values]
            if required_level and max(current_levels) and max(current_levels) < required_level:
                match, evidence = 0, values[0]
                reason = 'The profile lists a lower qualification than the stated requirement.'
            elif required_level and max(current_levels) == required_level:
                match, evidence = 70, values[0]
                reason = 'The qualification level aligns, but the requested subject or specialization is not fully demonstrated.'
            else:
                match, evidence = None, ''
                reason = 'Education information is present, but it does not establish this qualification either way.'
        else:
            match, reason = None, 'No education evidence is available.'
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
            evidence=[evidence], reason=reason, suggestion='Add the qualification and institution to your profile or CV.')

    if kind == 'experience':
        entries = profile.get('experience', [])
        evidence = _evidence_for(name, entries)
        requested_years = re.search(r'\b(\d+)\s*\+?\s*(?:years?|ans?)\b', name, re.I)
        explicit_years = [(int(found.group(1)), row.get('evidence', ''))
                          for row in entries if (found := re.search(r'\b(\d+)\s*\+?\s*(?:years?|ans?)\b', row.get('evidence', ''), re.I))]
        if requested_years and explicit_years:
            required = int(requested_years.group(1))
            achieved, evidence = max(explicit_years, key=lambda item: item[0])
            match = 100 if achieved >= required else 0 if mandatory else 60 if achieved > 0 else 0
            reason = f'The CV explicitly states {achieved} years; the requirement asks for {required}.'
        elif evidence:
            match, reason = 100, 'Relevant experience is explicitly described in the CV.'
        else:
            match = None
            reason = 'This experience is not demonstrated; the CV may omit relevant work or project history.'
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
            evidence=[evidence], reason=reason, suggestion='Describe relevant responsibilities, tools and dates in your CV.')

    if kind == 'language':
        languages = profile.get('languages', [])
        language_name = next((language for language in languages if _norm(language.get('name')) in _norm(name)), name.split()[0] if name else '')
        found = next((row for row in languages if _norm(row.get('name')) == _norm(language_name)), None)
        if found:
            requested_level = next((level for level in ('C2', 'C1', 'B2', 'B1', 'A2', 'A1') if level.casefold() in name.casefold()), '')
            achieved = found.get('proficiency', 'not stated')
            levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
            if not requested_level or achieved == 'not stated':
                match, reason = (100 if not requested_level else None), 'The language is listed in the CV; proficiency is not stated.'
            elif levels.index(achieved) >= levels.index(requested_level):
                match, reason = 100, f'The listed proficiency {achieved} meets {requested_level}.'
            else:
                gap = levels.index(requested_level) - levels.index(achieved)
                match = 0 if mandatory else 60 if gap == 1 else 0
                reason = f'The listed proficiency {achieved} is below the requested {requested_level}.'
            evidence = found.get('evidence', '')
        else:
            match, evidence, reason = None, '', 'This language is not demonstrated in the CV; it may still be known.'
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
            evidence=[evidence], reason=reason, suggestion='Add the language and a recognized proficiency level if applicable.')

    if kind == 'project':
        project_rows = profile.get('projects', [])
        evidence = _evidence_for(name, project_rows)
        partial = _partial_evidence(name, project_rows) if not evidence else ''
        match = 100 if evidence else 60 if partial else None
        evidence = evidence or partial
        reason = 'A relevant project description was found.' if match == 100 else 'Related project evidence was found, but it does not confirm the full criterion.' if partial else 'No matching project evidence was found in the CV.'
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
            evidence=[evidence], reason=reason, suggestion='Add a project entry that explains your contribution and tools.')

    if kind == 'location':
        value = ' '.join([profile_fields['location'], profile_fields['work_mode']]).strip()
        if value and _norm(name) in _norm(value):
            match, evidence, reason = 100, value, 'The profile location or work preference matches.'
        else:
            match, evidence, reason = None, '', 'The student has not recorded location or work arrangement preferences.'
        return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
            evidence=[evidence], reason=reason, suggestion='Add location preferences to the profile if you want this requirement evaluated.')

    # Other requirements are never guessed: only explicit textual evidence counts.
    all_evidence = skills + profile.get('projects', []) + profile.get('experience', []) + profile.get('education', [])
    evidence = _evidence_for(name, all_evidence)
    partial = _partial_evidence(name, all_evidence) if not evidence else ''
    match = 100 if evidence else 60 if partial else None
    evidence = evidence or partial
    reason = 'Explicit supporting text was found.' if match == 100 else 'Related evidence was found, but it does not fully confirm the criterion.' if partial else 'The requirement cannot be confirmed from available CV/profile evidence.'
    return _criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=match,
        evidence=[evidence], reason=reason, suggestion='Add specific supporting evidence to your profile or CV if applicable.')


def calculate_match(user, opportunity, *, cv_analysis=None, use_cache=True):
    """Score only the current user. No CV or insufficient reliable evidence => no precise score."""
    analysis = cv_analysis or analyze_student_cv(user)
    profile_data = analysis.get('data') or {}
    profile_signature = _profile_digest(user)
    cv_digest = analysis.get('cv_digest', '')
    if not cv_digest and hasattr(user, 'career_cv_analysis'):
        cv_digest = user.career_cv_analysis.cv_digest
    if use_cache and analysis.get('status') == 'ready' and cv_digest and opportunity.pk:
        cached = CareerMatchCache.objects.filter(user=user, opportunity=opportunity).first()
        if cached and cached.cv_digest == cv_digest and cached.profile_digest == profile_signature and cached.opportunity_updated_at == opportunity.updated_at:
            return cached.result

    profile_fields = {
        'skills': list(user.skills or []), 'education': [value for value in (user.study_level, user.specialty) if value],
        'location': '', 'work_mode': '',
    }
    skills = list(opportunity.skills.all())
    custom = list(opportunity.requirements.all())
    criteria = []
    for skill in skills:
        criteria.append((skill.name, 'skill', skill.weight, skill.kind == OpportunitySkill.Kind.REQUIRED and skill.verified))
    custom_kinds = set()
    for requirement in custom:
        custom_kinds.add(requirement.kind)
        criteria.append((requirement.name, requirement.kind, requirement.weight, requirement.mandatory))

    # Backward-compatible legacy fields are evaluated with default weights only when an
    # organizer has not configured a corresponding typed requirement.
    legacy = [
        ('education', opportunity.education, CareerRequirement.Kind.EDUCATION),
        ('experience', opportunity.experience, CareerRequirement.Kind.EXPERIENCE),
        ('location', ', '.join(x for x in (opportunity.location, opportunity.get_work_mode_display()) if x and x != 'Not specified'), CareerRequirement.Kind.LOCATION),
    ]
    for weight_key, value, kind in legacy:
        if value and kind not in custom_kinds:
            criteria.append((value, kind, Decimal(str(LEGACY_WEIGHTS.get(weight_key, 0))), False))
    if CareerRequirement.Kind.LANGUAGE not in custom_kinds:
        language_list = opportunity.languages or []
        if language_list:
            language_weight = Decimal(str(LEGACY_WEIGHTS.get('languages', 0))) / len(language_list)
            criteria.extend((language, CareerRequirement.Kind.LANGUAGE, language_weight, False) for language in language_list)

    if analysis.get('status') != 'ready':
        breakdown = [_criterion_result(name=name, kind=kind, weight=weight, mandatory=mandatory, match=None,
            evidence=[], reason=('Upload a readable, text-based PDF CV to evaluate this requirement.' if analysis.get('status') == 'missing'
                                 else 'The existing CV could not be read. Upload a text-based PDF; scanned-image OCR is not enabled.'),
            suggestion='Update your private CV in your HackFlow profile.') for name, kind, weight, mandatory in criteria]
        result = {'score': None, 'coverage': 0, 'requirements_evaluated': 0, 'missing_evidence_count': len(breakdown),
            'mandatory_status': 'unknown', 'mandatory': 'unverified', 'eligibility': {'status': 'unverified'},
            'breakdown': breakdown, 'matched_skills': [], 'missing_required_skills': [],
            'missing_preferred_skills': [], 'recommendations': ['Upload a readable CV in your profile to see a compatibility score.'],
            'score_state': analysis.get('status', 'missing')}
        return result

    breakdown = [_evaluate(name, kind, Decimal(str(weight)), mandatory, profile_data, profile_fields)
                 for name, kind, weight, mandatory in criteria]
    positive_total = sum((Decimal(str(row['weight'])) for row in breakdown if Decimal(str(row['weight'])) > 0), Decimal(0))
    evaluated = [row for row in breakdown if row['match_pct'] is not None and row['weight'] > 0]
    evaluated_weight = sum((Decimal(str(row['weight'])) for row in evaluated), Decimal(0))
    coverage = round(float(evaluated_weight / positive_total * 100)) if positive_total else 0
    score = round(sum(row['match_pct'] * float(row['weight']) for row in evaluated) / float(evaluated_weight)) if evaluated_weight else None
    if score is not None and coverage < MIN_CONFIDENT_COVERAGE:
        score, score_state = None, 'insufficient_data'
    else:
        score_state = 'scored' if score is not None else 'insufficient_data'
    mandatory_results = [row for row in breakdown if row['mandatory']]
    if any(row['status'] == 'mandatory_not_met' for row in mandatory_results):
        mandatory_status = 'failed'
    elif any(row['match_pct'] is None or row['status'] == 'partial' for row in mandatory_results):
        mandatory_status = 'unverified'
    else:
        mandatory_status = 'satisfied'
    missing = [row for row in breakdown if row['match_pct'] is None]
    result = {
        'score': score, 'coverage': coverage, 'requirements_evaluated': len(evaluated),
        'missing_evidence_count': len(missing), 'mandatory_status': mandatory_status,
        'mandatory': 'failed' if mandatory_status == 'failed' else 'unverified' if mandatory_status == 'unverified' else 'satisfied',
        'eligibility': {'status': mandatory_status,
            'verified_missing': [row['requirement'] for row in mandatory_results if row['status'] == 'mandatory_not_met'],
            'unverified': [row['requirement'] for row in mandatory_results if row['match_pct'] is None]},
        'breakdown': breakdown,
        'matched_skills': [row['requirement'] for row in breakdown if row['type'] == 'skill' and row['match_pct'] == 100],
        'missing_required_skills': [row['requirement'] for row in breakdown if row['type'] == 'skill' and row['mandatory'] and row['match_pct'] is None],
        'missing_preferred_skills': [row['requirement'] for row in breakdown if row['type'] == 'skill' and not row['mandatory'] and row['match_pct'] is None],
        'recommendations': list(dict.fromkeys(row['suggestion'] for row in breakdown
            if row['suggestion'] and (row['match_pct'] is None or 0 < row['match_pct'] < 85))),
        'score_state': score_state,
    }
    if use_cache and cv_digest and opportunity.pk:
        CareerMatchCache.objects.update_or_create(user=user, opportunity=opportunity, defaults={
            'cv_digest': cv_digest, 'profile_digest': profile_signature,
            'opportunity_updated_at': opportunity.updated_at, 'result': result,
        })
    return result


def calculate_matches(user, opportunities, *, cv_analysis=None):
    """Bulk-load per-student cache rows, calculate misses, and persist in two queries."""
    opportunities = list(opportunities)
    if not opportunities:
        return {}
    analysis = cv_analysis or analyze_student_cv(user)
    digest = analysis.get('cv_digest', '')
    signature = _profile_digest(user)
    cached_rows = {row.opportunity_id: row for row in CareerMatchCache.objects.filter(
        user=user, opportunity_id__in=[offer.pk for offer in opportunities])}
    results, creates, updates = {}, [], []
    for offer in opportunities:
        row = cached_rows.get(offer.pk)
        if (row and digest and analysis.get('status') == 'ready' and row.cv_digest == digest
                and row.profile_digest == signature and row.opportunity_updated_at == offer.updated_at):
            results[offer.pk] = row.result
            continue
        result = calculate_match(user, offer, cv_analysis=analysis, use_cache=False)
        results[offer.pk] = result
        if digest and analysis.get('status') == 'ready':
            if row:
                row.cv_digest, row.profile_digest = digest, signature
                row.opportunity_updated_at, row.result = offer.updated_at, result
                updates.append(row)
            else:
                creates.append(CareerMatchCache(user=user, opportunity=offer, cv_digest=digest,
                    profile_digest=signature, opportunity_updated_at=offer.updated_at, result=result))
    if creates:
        CareerMatchCache.objects.bulk_create(creates, ignore_conflicts=True)
    if updates:
        CareerMatchCache.objects.bulk_update(updates, ['cv_digest', 'profile_digest', 'opportunity_updated_at', 'result', 'updated_at'])
    return results
