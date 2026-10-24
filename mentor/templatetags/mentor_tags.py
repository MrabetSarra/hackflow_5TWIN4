from django import template

from student.models import MentorRequest

from ..models import MentorAssignment

register = template.Library()


@register.simple_tag(takes_context=True)
def mentor_counts(context):
    """Compteurs de la barre latérale mentor (tickets en attente, équipes suivies)."""
    user = context['request'].user
    if not user.is_authenticated:
        return {'pending': 0, 'followed': 0}
    return {
        'pending': MentorRequest.objects.filter(status=MentorRequest.Status.PENDING).count(),
        'followed': MentorAssignment.objects.filter(mentor=user).count(),
    }
