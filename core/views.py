from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def csrf_failure(request, reason=''):
    """Give users a safe way to reopen forms after their CSRF cookie rotates."""
    referer = request.META.get('HTTP_REFERER', '')
    retry_url = referer if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) else reverse('core:landing')
    response = render(request, 'core/csrf_failure.html', {'retry_url': retry_url}, status=403)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

def landing(request):
    """Build the public landing page from the current HackFlow records."""
    from django.contrib.auth import get_user_model
    from django.db.models import Count, Exists, OuterRef
    from django.utils import timezone

    from student.models import Hackathon, HackathonRegistration, Team, TeamMembership

    User = get_user_model()
    now = timezone.now()
    hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    if not hackathon:
        hackathon = Hackathon.objects.order_by('-starts_at', '-pk').first()

    team_queryset = Team.objects.select_related('hackathon').annotate(
        current_member_count=Count('memberships', distinct=True),
    ).prefetch_related('memberships__user')
    student_pool = User.objects.filter(role='student', is_active=True)
    if hackathon:
        team_queryset = team_queryset.filter(hackathon=hackathon)
        registered_ids = HackathonRegistration.objects.filter(hackathon=hackathon).values('user_id')
        student_pool = student_pool.filter(pk__in=registered_ids)

    teams = list(team_queryset.order_by('name'))
    teams_count = len(teams)
    participants_count = student_pool.count()
    mentors_count = User.objects.filter(role='mentor', is_active=True).count()
    available_places = sum(max(0, team.max_members - team.current_member_count) for team in teams)
    unassigned_count = student_pool.annotate(
        has_team=Exists(TeamMembership.objects.filter(
            user_id=OuterRef('pk'),
            team__hackathon=hackathon,
        ) if hackathon else TeamMembership.objects.filter(user_id=OuterRef('pk'))),
    ).filter(has_team=False).count()

    profile_rows = student_pool.values_list('skills', 'preferred_roles')
    profiled_count = 0
    for skills, roles in profile_rows:
        skills = skills if isinstance(skills, list) else []
        roles = roles if isinstance(roles, list) else []
        if skills or roles:
            profiled_count += 1

    matching_teams = []
    for team in sorted(teams, key=lambda item: (item.current_member_count >= item.max_members, item.name.casefold()))[:4]:
        matching_teams.append({
            'name': team.name,
            'category': team.category or 'Thématique à définir',
            'project_name': team.project_name,
            'member_count': team.current_member_count,
            'max_members': team.max_members,
            'places_left': max(0, team.max_members - team.current_member_count),
            'occupancy_percent': round(min(team.current_member_count, team.max_members) * 100 / team.max_members) if team.max_members else 0,
            'table': team.table_number or team.room,
            'seeking_skill': team.seeking_skill,
        })

    if not hackathon:
        event_state = 'none'
    elif now < hackathon.starts_at:
        event_state = 'upcoming'
    elif now <= hackathon.ends_at:
        event_state = 'live'
    else:
        event_state = 'ended'

    context = {
        'hackathon': hackathon,
        'event_state': event_state,
        'tagline': 'HackFlow réunit les participants, les équipes et les mentors dans un espace unique pour organiser le hackathon.',
        'stats': [
            {'label': 'Participants inscrits', 'value': f'{participants_count:,}'.replace(',', ' '), 'icon': 'bi-people-fill', 'color': 'primary'},
            {'label': 'Équipes créées', 'value': f'{teams_count:,}'.replace(',', ' '), 'icon': 'bi-diagram-3-fill', 'color': 'accent'},
            {'label': 'Mentors actifs', 'value': f'{mentors_count:,}'.replace(',', ' '), 'icon': 'bi-lightbulb-fill', 'color': 'success'},
            {'label': 'Places disponibles', 'value': f'{available_places:,}'.replace(',', ' '), 'icon': 'bi-person-plus-fill', 'color': 'warning'},
        ],
        'teams_count': teams_count,
        'participants_count': participants_count,
        'unassigned_count': unassigned_count,
        'profiled_count': profiled_count,
        'available_places': available_places,
        'matching_teams': matching_teams,
        'featured_team': matching_teams[0] if matching_teams else None,
        'steps': [
            {'num': '01', 'title': 'Créez votre profil', 'desc': 'Ajoutez vos compétences, vos rôles préférés et vos disponibilités.', 'badge': 'Profil participant'},
            {'num': '02', 'title': 'Formez une équipe', 'desc': 'Rejoignez une équipe ou consultez les recommandations de composition.', 'badge': 'Matching assisté'},
            {'num': '03', 'title': 'Organisez le projet', 'desc': 'Répartissez les tâches, suivez les jalons et échangez avec vos coéquipiers.', 'badge': 'Espace équipe'},
            {'num': '04', 'title': 'Présentez votre projet', 'desc': 'Déposez votre livrable et partagez vos liens avec le jury.', 'badge': 'Dépôt de projet'},
        ],
        'faq': [
            {'q': 'Puis-je participer sans équipe ?', 'a': 'Oui. Créez votre profil et rejoignez une équipe disponible. Les organisateurs peuvent aussi proposer une composition à partir des compétences et préférences renseignées.'},
            {'q': 'Comment trouver une équipe qui correspond à mon profil ?', 'a': 'Les équipes peuvent indiquer les compétences recherchées. Le matching tient compte des compétences, rôles préférés, thématiques et disponibilités renseignés.'},
            {'q': 'Où suivre les informations de l’événement ?', 'a': 'Les annonces publiées pour le hackathon apparaissent dans les espaces des participants. Les dates et le lieu de l’événement sont affichés ci-dessus lorsqu’ils sont configurés.'},
            {'q': 'Comment remettre un projet au jury ?', 'a': 'L’équipe peut renseigner sa description, ses liens de démonstration et déposer son archive depuis l’espace de soumission.'},
        ],
    }
    return render(request, 'core/landing.html', context)

