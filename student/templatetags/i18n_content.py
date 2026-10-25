from django import template
from django.utils.translation import gettext

register = template.Library()


@register.filter
def localized_milestone(title):
    """Translate known seeded milestones without changing stored user data."""
    seeded_titles = {
        'Kick-off & Ideation',
        'Concept review with a mentor',
        'Milestone 1: Architecture & Wireframes',
        'Milestone 2: Functional MVP submission',
        'Final Pitch to the Jury',
    }
    if title in seeded_titles:
        return gettext(title)
    return title
