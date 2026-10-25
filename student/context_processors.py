from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Hackathon, MentorRequest, Notification, Submission, TeamMembership


def student_globals(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    role = getattr(user, 'role', None)
    user_notifications = Notification.objects.filter(user=user)
    user_unread_count = user_notifications.filter(is_read=False).count()

    context = {
        'user_notifications': user_notifications[:5],
        'user_notification_count': user_unread_count,
    }

    if role == 'student':
        initials = ''.join(part[:1].upper() for part in (user.first_name, user.last_name) if part)
        if not initials:
            initials = user.username[:2].upper()
        hackathon = Hackathon.objects.filter(is_active=True).first()
        membership = TeamMembership.objects.filter(user=user).select_related('team').first()
        team_member_count = membership.team.member_count if membership else 0
        team_max_members = membership.team.max_members if membership else 0
        remaining = max(hackathon.ends_at - timezone.now(), timezone.timedelta()) if hackathon else None
        if remaining:
            seconds = int(remaining.total_seconds())
            countdown = f'{seconds // 3600}h{(seconds % 3600) // 60:02d}mn'
        else:
            countdown = '—'
        context.update({
            'student_initials': initials,
            'student_notifications': user_notifications[:5],
            'student_notification_count': user_unread_count,
            'student_sprint_countdown': countdown,
            'student_sprint_deadline': hackathon.ends_at.isoformat() if hackathon else '',
            'student_team_member_count': team_member_count,
            'student_team_max_members': team_max_members,
        })
    elif role in ('admin', 'organization'):
        User = get_user_model()
        admin_alerts = []
        try:
            unassigned_count = User.objects.filter(role='student', is_active=True, team_memberships__isnull=True).count()
            if unassigned_count > 0:
                admin_alerts.append({
                    'title': f"{unassigned_count} participant{'' if unassigned_count == 1 else 's'} sans équipe",
                    'message': "Des étudiants inscrits ne sont rattachés à aucune équipe.",
                    'url': '/cockpit/participants/',
                    'icon': 'bi-people-fill',
                    'color': 'text-warning',
                })
        except Exception:
            pass

        try:
            pending_submissions = Submission.objects.filter(status=Submission.Status.SUBMITTED).count()
            if pending_submissions > 0:
                admin_alerts.append({
                    'title': f"{pending_submissions} livrable{'' if pending_submissions == 1 else 's'} en attente",
                    'message': "Des soumissions d’équipes attendent une évaluation.",
                    'url': '/cockpit/teams/',
                    'icon': 'bi-cloud-arrow-up-fill',
                    'color': 'text-info',
                })
        except Exception:
            pass

        try:
            pending_requests = MentorRequest.objects.filter(status=MentorRequest.Status.PENDING).count()
            if pending_requests > 0:
                admin_alerts.append({
                    'title': f"{pending_requests} demande{'' if pending_requests == 1 else 's'} de mentorat",
                    'message': "Des équipes attendent l'aide d'un mentor.",
                    'url': '/cockpit/teams/',
                    'icon': 'bi-headset',
                    'color': 'text-primary',
                })
        except Exception:
            pass

        for notif in user_notifications[:5]:
            admin_alerts.append({
                'title': notif.title or 'Notification',
                'message': notif.message,
                'url': notif.url,
                'icon': notif.icon or 'bi-bell-fill',
                'color': 'text-success',
            })

        context.update({
            'admin_alerts': admin_alerts,
            'admin_notification_count': len(admin_alerts),
        })
    elif role == 'mentor':
        context.update({
            'mentor_notifications': user_notifications[:5],
            'mentor_notification_count': user_unread_count,
        })

    return context
