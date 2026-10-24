"""Eligibility is separate from similarity: matching must never imply a guarantee."""


def evaluate_eligibility(user, opportunity, missing_required_skills):
    profile_skills = {str(skill).casefold().strip() for skill in (user.skills or [])}
    required = list(opportunity.skills.filter(kind='required'))
    verified_missing = [skill.name for skill in required
                        if skill.verified and skill.name in missing_required_skills and profile_skills]
    unverified = [skill.name for skill in required if not skill.verified]
    if required and not profile_skills:
        unverified.extend(skill.name for skill in required if skill.name not in unverified)
    if verified_missing:
        return {'status': 'failed', 'verified_missing': verified_missing, 'unverified': unverified}
    if unverified or opportunity.languages:
        return {'status': 'unverified', 'verified_missing': [], 'unverified': unverified}
    return {'status': 'satisfied', 'verified_missing': [], 'unverified': []}
