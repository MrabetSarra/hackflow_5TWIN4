from django import template

from student.models import MentorRequest

from ..models import MentorAssignment

register = template.Library()

# Couleur Bootstrap par statut (demandes d'aide, sessions, soumissions).
STATUS_COLORS = {
    'pending': 'warning', 'accepted': 'primary', 'resolved': 'success',
    'planned': 'info', 'confirmed': 'success', 'done': 'secondary', 'cancelled': 'danger',
    'draft': 'secondary', 'submitted': 'primary', 'approved': 'success', 'revision': 'warning',
}


@register.filter
def status_badge(status):
    """Classes d'un badge de statut ; les variantes « emphasis » gardent un contraste AA en clair et en sombre."""
    color = STATUS_COLORS.get(status, 'secondary')
    return f'bg-{color}-subtle text-{color}-emphasis border border-{color}-subtle'


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
