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


# Pages (url_name du namespace « mentor ») qui activent chaque lien de la barre latérale.
# Des listes et non une chaîne : « 'list' in 'sessions_list …' » serait vrai par sous-chaîne.
NAV_PAGES = {
    'team_pages': ['teams_list', 'team_detail'],
    'session_pages': ['sessions_list', 'session_create', 'session_update', 'session_delete'],
    'submission_pages': ['submissions', 'evaluation_create'],
    'evaluation_pages': ['evaluations', 'evaluation_detail', 'evaluation_update', 'evaluation_delete'],
}


@register.simple_tag(takes_context=True)
def mentor_counts(context):
    """Compteurs de la barre latérale mentor (tickets en attente, équipes suivies) et pages actives."""
    user = context['request'].user
    if not user.is_authenticated:
        return {'pending': 0, 'followed': 0, **NAV_PAGES}
    return {
        'pending': MentorRequest.objects.filter(status=MentorRequest.Status.PENDING).count(),
        'followed': MentorAssignment.objects.filter(mentor=user).count(),
        **NAV_PAGES,
    }
