from django.utils import timezone

from .models import Hackathon, Notification, TeamMembership


def student_globals(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated or getattr(request.user, 'role', None) != 'student':
        return {}
    initials = ''.join(part[:1].upper() for part in (request.user.first_name, request.user.last_name) if part)
    if not initials:
        initials = request.user.username[:2].upper()
    notifications = Notification.objects.filter(user=request.user)
    hackathon = Hackathon.objects.filter(is_active=True).first()
    membership = TeamMembership.objects.filter(user=request.user).select_related('team').first()
    team_member_count = membership.team.member_count if membership else 0
    team_max_members = membership.team.max_members if membership else 0
    remaining = max(hackathon.ends_at - timezone.now(), timezone.timedelta()) if hackathon else None
    if remaining:
        seconds = int(remaining.total_seconds())
        countdown = f'{seconds // 3600}h{(seconds % 3600) // 60:02d}mn'
    else:
        countdown = '—'
    return {'student_initials': initials, 'student_notifications': notifications[:5],
            'student_notification_count': notifications.filter(is_read=False).count(), 'student_sprint_countdown': countdown,
            'student_sprint_deadline': hackathon.ends_at.isoformat() if hackathon else '',
            'student_team_member_count': team_member_count, 'student_team_max_members': team_max_members}
