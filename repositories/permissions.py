from django.http import Http404

from student.models import TeamMembership


def student_team(user):
    if not user.is_authenticated or getattr(user, 'role', None) != 'student':
        return None
    membership = TeamMembership.objects.filter(user=user).select_related('team').first()
    return membership.team if membership else None


def get_team_repository(user, slug):
    from .models import Repository
    if getattr(user, 'role', None) == 'student':
        team = student_team(user)
        if not team:
            raise Http404
        try:
            return Repository.objects.get(team=team, slug=slug)
        except Repository.DoesNotExist as exc:
            raise Http404 from exc
    if getattr(user, 'role', None) == 'mentor':
        from student.models import MentorRequest
        repository = Repository.objects.filter(slug=slug, team__mentor_requests__mentor=user,
            team__mentor_requests__status=MentorRequest.Status.ACCEPTED).distinct().first()
        if repository:
            return repository
        raise Http404
    raise Http404
