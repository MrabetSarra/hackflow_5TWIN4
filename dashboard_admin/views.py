import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Announcement, Hackathon, HackathonRegistration, MentorRequest, Submission, Team, TeamMembership
from career_opportunities.models import ApplicationHistory, CareerApplication
from .forms import AnnouncementForm, HackathonForm

@role_required('admin', 'organization')
def dashboard(request):
    """
    Cockpit principal pour les organisateurs du hackathon.
    """
    context = {
        'kpis': [
            {'label': 'Participants Inscrits', 'value': '520', 'icon': 'bi-people-fill', 'color': 'primary', 'sub': '+45 depuis hier'},
            {'label': 'Équipes Actives', 'value': '92', 'icon': 'bi-diagram-3-fill', 'color': 'success', 'sub': '84 complètes à 100%'},
            {'label': 'Participants Placés', 'value': '94%', 'icon': 'bi-pie-chart-fill', 'color': 'accent', 'sub': '31 sans équipe'},
            {'label': 'Interventions Mentors', 'value': '34', 'icon': 'bi-headset', 'color': 'warning', 'sub': 'Temps moyen : 14 min'},
        ],
        'challenges_stats': [
            {'name': 'Climat & Transition Écologique', 'count': 28, 'percent': 30},
            {'name': 'IA & Productivité Étudiante', 'count': 26, 'percent': 28},
            {'name': 'Santé & Bien-être', 'count': 20, 'percent': 22},
            {'name': 'FinTech & Inclusion', 'count': 18, 'percent': 20},
        ],
        'live_activity': [
            {'event': 'Nouvelle équipe formée : "CodeCraft"', 'time': 'Il y a 3 min', 'icon': 'bi-people-fill', 'color': 'success'},
            {'event': 'Ticket mentor #T-108 ouvert par "FinEd"', 'time': 'Il y a 8 min', 'icon': 'bi-bell-fill', 'color': 'warning'},
            {'event': 'Livrable intermédiaire déposé par "EcoTrack"', 'time': 'Il y a 14 min', 'icon': 'bi-cloud-check-fill', 'color': 'primary'},
            {'event': 'Nouveau participant inscrit : Sarah K. (Polytech)', 'time': 'Il y a 22 min', 'icon': 'bi-person-plus-fill', 'color': 'info'},
        ],
        'pending_alerts': [
            {'msg': '31 étudiants sont encore orphelins d\'équipe.', 'action': 'Lancer le matching auto', 'urgent': True},
            {'msg': 'Table 14 : Signalement de problème de connexion WiFi.', 'action': 'Notifier support réseau', 'urgent': False},
        ]
    }
    return render(request, 'dashboard_admin/dashboard.html', context)


@role_required('admin', 'organization')
def teams(request):
    """
    Gestion des équipes du hackathon.
    """
    context = {
        'teams_list': [
            {
                'name': 'EcoTrack',
                'challenge': 'Climat & Énergie',
                'leader': 'Camille Laurent',
                'members_count': 4,
                'table': 'Table 14',
                'mentor': 'Dr. Marc Dubois',
                'submission_status': 'Brouillon prêt',
                'submission_color': 'warning',
                'progress': 68,
            },
            {
                'name': 'MediConnect',
                'challenge': 'Santé & Bien-être',
                'leader': 'Karim Bensaid',
                'members_count': 3,
                'table': 'Table 08',
                'mentor': 'Dr. Marc Dubois',
                'submission_status': 'Non soumis',
                'submission_color': 'danger',
                'progress': 45,
            },
            {
                'name': 'StudyBuddy AI',
                'challenge': 'Éducation & IA',
                'leader': 'Claire Fontaine',
                'members_count': 5,
                'table': 'Table 19',
                'mentor': 'Thomas Vasseur',
                'submission_status': 'Validé & Rendu',
                'submission_color': 'success',
                'progress': 88,
            },
            {
                'name': 'FinEd',
                'challenge': 'FinTech Éducative',
                'leader': 'Julien Fabre',
                'members_count': 4,
                'table': 'Table 21',
                'mentor': 'Sarah Benali',
                'submission_status': 'En cours',
                'submission_color': 'secondary',
                'progress': 55,
            },
        ]
    }
    return render(request, 'dashboard_admin/teams.html', context)


@role_required('admin', 'organization')
def announcements(request):
    active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at').first()
    form = AnnouncementForm(request.POST or None)

    if request.method == 'POST':
        if not active_hackathon:
            messages.error(request, 'Aucun hackathon actif : créez ou activez un événement avant de publier.')
            form = AnnouncementForm()
        elif form.is_valid():
            announcement = form.save(commit=False)
            announcement.hackathon = active_hackathon
            announcement.author = (request.user.get_full_name() or request.user.username)[:120]
            announcement.is_draft = request.POST.get('submit_action') == 'draft'
            if not announcement.is_draft and announcement.scheduled_at:
                announcement.published_at = announcement.scheduled_at
            announcement.save()
            if announcement.is_draft:
                messages.success(request, 'Brouillon enregistre.')
            elif announcement.is_scheduled:
                messages.success(request, 'Annonce programmee.')
            else:
                messages.success(request, 'Annonce publiee.')
            return redirect('dashboard_admin:announcements')

    queryset = Announcement.objects.select_related('hackathon').annotate(
        effective_at=Coalesce('scheduled_at', 'published_at'),
    ).order_by('-effective_at', '-pk')
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    audience = request.GET.get('audience', '').strip()
    priority = request.GET.get('priority', '').strip()
    status = request.GET.get('status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(body__icontains=query))
    if category:
        queryset = queryset.filter(category__iexact=category)
    if audience in dict(Announcement.Audience.choices):
        queryset = queryset.filter(audience=audience)
    if priority in dict(Announcement.Priority.choices):
        queryset = queryset.filter(priority=priority)
    if status == 'draft':
        queryset = queryset.filter(is_draft=True)
    elif status == 'scheduled':
        queryset = queryset.filter(is_draft=False, scheduled_at__gt=timezone.now())
    elif status == 'published':
        queryset = queryset.filter(is_draft=False).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=timezone.now()))
    parsed_from, parsed_to = parse_date(date_from), parse_date(date_to)
    if parsed_from:
        queryset = queryset.filter(effective_at__date__gte=parsed_from)
    if parsed_to:
        queryset = queryset.filter(effective_at__date__lte=parsed_to)
    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    now = timezone.now()
    all_announcements = Announcement.objects.all()
    context = {
        'form': form,
        'active_hackathon': active_hackathon,
        'past_announcements': page_obj.object_list,
        'page_obj': page_obj,
        'filter_values': {'q': query, 'category': category, 'audience': audience, 'priority': priority, 'status': status,
                          'date_from': date_from, 'date_to': date_to},
        'announcement_categories': Announcement.objects.exclude(category='').values_list('category', flat=True).distinct().order_by('category'),
        'announcement_stats': {
            'total': all_announcements.count(),
            'published': all_announcements.filter(is_draft=False).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)).count(),
            'week': all_announcements.filter(is_draft=False, published_at__gte=now - timedelta(days=7)).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)).count(),
            'urgent': all_announcements.filter(is_draft=False, priority=Announcement.Priority.URGENT).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)).count(),
            'scheduled': all_announcements.filter(is_draft=False, scheduled_at__gt=now).count(),
            'drafts': all_announcements.filter(is_draft=True).count(),
        },
    }
    return render(request, 'dashboard_admin/announcements.html', context)

@role_required('admin', 'organization')
def judging(request):
    """
    Grille de notation du jury et classement final.
    """
    context = {
        'podium': [
            {
                'rank': 1,
                'team': 'StudyBuddy AI',
                'score': 18.75,
                'category': 'Éducation & IA',
                'award': '1er Prix (5 000 €)',
                'badge_color': 'warning',
            },
            {
                'rank': 2,
                'team': 'EcoTrack',
                'score': 18.20,
                'category': 'Climat & Énergie',
                'award': '2e Prix (3 000 €)',
                'badge_color': 'secondary',
            },
            {
                'rank': 3,
                'team': 'MediConnect',
                'score': 17.40,
                'category': 'Santé & Bien-être',
                'award': '3e Prix (2 000 €)',
                'badge_color': 'info',
            },
        ],
        'teams_ranking': [
            {
                'rank': 1,
                'team': 'StudyBuddy AI',
                'innovation': 4.8,
                'tech': 4.9,
                'design': 4.5,
                'pitch': 4.55,
                'total': 18.75,
            },
            {
                'rank': 2,
                'team': 'EcoTrack',
                'innovation': 4.7,
                'tech': 4.6,
                'design': 4.9,
                'pitch': 4.0,
                'total': 18.20,
            },
            {
                'rank': 3,
                'team': 'MediConnect',
                'innovation': 4.5,
                'tech': 4.3,
                'design': 4.4,
                'pitch': 4.2,
                'total': 17.40,
            },
            {
                'rank': 4,
                'team': 'FinEd',
                'innovation': 4.2,
                'tech': 4.1,
                'design': 4.3,
                'pitch': 4.4,
                'total': 17.00,
            },
            {
                'rank': 5,
                'team': 'SafeCity',
                'innovation': 4.0,
                'tech': 3.9,
                'design': 4.1,
                'pitch': 4.2,
                'total': 16.20,
            },
        ]
    }
    return render(request, 'dashboard_admin/judging.html', context)


# Live participant management overrides the original presentation-only demo view.
@role_required('admin', 'organization')
def participants(request):
    rows = _participant_rows(request.GET)
    page = Paginator(rows, 25).get_page(request.GET.get('page'))
    teams = Team.objects.select_related('hackathon').order_by('hackathon__name', 'name')
    return render(request, 'dashboard_admin/participants.html', {
        'participants_list': page.object_list,
        'page_obj': page,
        'teams': teams,
        'participants_count': get_user_model().objects.filter(role__in=('student', 'mentor')).count(),
        'filters': {
            'q': request.GET.get('q', '').strip(),
            'role': request.GET.get('role', ''),
            'status': request.GET.get('status', ''),
        },
        'role_filter': request.GET.get('role', ''),
        'status_filter': request.GET.get('status', ''),
    })


def _participant_rows(params):
    User = get_user_model()
    users = User.objects.filter(role__in=('student', 'mentor')).annotate(
        has_team=Exists(TeamMembership.objects.filter(user_id=OuterRef('pk'))),
    ).prefetch_related('team_memberships__team').order_by('last_name', 'first_name', 'username')

    role_filter = params.get('role', '')
    if role_filter in ('student', 'mentor'):
        users = users.filter(role=role_filter)
    status_filter = params.get('status', '')
    if status_filter == 'assigned':
        users = users.filter(role='student', has_team=True, is_active=True)
    elif status_filter == 'unassigned':
        users = users.filter(role='student', has_team=False, is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    elif status_filter == 'active':
        users = users.filter(is_active=True)

    search = params.get('q', '').strip().casefold()
    rows = []
    for user in users:
        memberships = list(user.team_memberships.all())
        team_names = [membership.team.name for membership in memberships]
        if not user.is_active:
            status, status_color = 'Inactif', 'secondary'
        elif user.role == 'student' and memberships:
            status, status_color = 'En équipe', 'success'
        elif user.role == 'student':
            status, status_color = 'Sans équipe', 'danger'
        else:
            status, status_color = 'Actif', 'primary'
        skills = user.skills if isinstance(user.skills, list) else []
        full_name = user.get_full_name().strip() or user.username
        row = {
            'user': user,
            'id': user.pk,
            'name': full_name,
            'email': user.email,
            'school': user.school,
            'role': user.get_role_display(),
            'role_key': user.role,
            'team_names': team_names,
            'team_id': memberships[0].team_id if len(memberships) == 1 else None,
            'skills': skills,
            'status': status,
            'status_color': status_color,
        }
        searchable = ' '.join((full_name, user.username, user.email, user.school, user.specialty, *skills)).casefold()
        if search and search not in searchable:
            continue
        rows.append(row)
    return rows


@role_required('admin', 'organization')
def participants_export(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="hackflow-participants.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Nom', 'E-mail', 'Établissement', 'Rôle', 'Équipe(s)', 'Compétences', 'Statut'])
    for row in _participant_rows(request.GET):
        writer.writerow([
            row['name'], row['email'], row['school'], row['role'],
            ', '.join(row['team_names']) or 'Aucune', ', '.join(row['skills']), row['status'],
        ])
    return response


@role_required('admin', 'organization')
def participant_detail(request, user_id):
    User = get_user_model()
    participant = get_object_or_404(
        User.objects.prefetch_related('team_memberships__team'),
        pk=user_id, role__in=('student', 'mentor'),
    )
    memberships = list(participant.team_memberships.select_related('team', 'team__hackathon').order_by('-joined_at'))
    history = [{
        'at': participant.date_joined,
        'title': 'Joined HackFlow',
        'detail': 'Participant account created',
        'icon': 'bi-person-plus',
        'tone': 'primary',
        'category': 'Account',
    }]
    for registration in HackathonRegistration.objects.filter(user=participant).select_related('hackathon'):
        history.append({
            'at': registration.registered_at,
            'title': 'Registered for a hackathon',
            'detail': registration.hackathon.name,
            'icon': 'bi-ticket-perforated',
            'tone': 'info',
            'category': 'Registration',
        })
    for membership in memberships:
        hackathon = membership.team.hackathon.name if membership.team.hackathon else 'HackFlow'
        history.append({
            'at': membership.joined_at,
            'title': 'Joined a team',
            'detail': f'{membership.team.name} · {hackathon}',
            'icon': 'bi-people',
            'tone': 'success',
            'category': 'Team',
        })
    for submission in Submission.objects.filter(submitted_by=participant).select_related('team', 'milestone').exclude(submitted_at__isnull=True):
        history.append({
            'at': submission.submitted_at,
            'title': 'Submitted a project milestone',
            'detail': f'{submission.milestone.title} · {submission.team.name} · {submission.get_status_display()}',
            'icon': 'bi-cloud-check',
            'tone': 'warning',
            'category': 'Project',
        })
    if participant.role == 'student':
        for request_item in MentorRequest.objects.filter(student=participant).select_related('team'):
            team_name = f' · {request_item.team.name}' if request_item.team else ''
            history.append({
                'at': request_item.created_at,
                'title': 'Requested mentor support',
                'detail': f'{request_item.subject}{team_name} · {request_item.get_status_display()}',
                'icon': 'bi-life-preserver',
                'tone': 'danger' if request_item.urgency == MentorRequest.Urgency.BLOCKING else 'info',
                'category': 'Mentor support',
            })
    applications = CareerApplication.objects.filter(user=participant).select_related('opportunity').prefetch_related('history')
    for application in applications:
        events = list(application.history.all())
        if events:
            for event in events:
                history.append({
                    'at': event.created_at,
                    'title': f'Career application · {event.get_new_status_display()}',
                    'detail': f'{application.opportunity.title} · {application.opportunity.company}',
                    'icon': 'bi-briefcase',
                    'tone': 'primary',
                    'category': 'Career',
                })
        else:
            history.append({
                'at': application.created_at,
                'title': 'Started a career application',
                'detail': f'{application.opportunity.title} · {application.opportunity.company}',
                'icon': 'bi-briefcase',
                'tone': 'primary',
                'category': 'Career',
            })
    history.sort(key=lambda event: event['at'], reverse=True)
    return render(request, 'dashboard_admin/participant_detail.html', {
        'participant': participant,
        'memberships': memberships,
        'history': history,
        'history_count': len(history),
        'applications_count': applications.count(),
    })


@require_POST
@role_required('admin', 'organization')
def participant_set_team(request, user_id):
    User = get_user_model()
    participant = get_object_or_404(User, pk=user_id, role='student')
    team_id = request.POST.get('team_id', '').strip()
    if not team_id:
        TeamMembership.objects.filter(user=participant).delete()
        messages.success(request, f"L'affectation de {participant.get_full_name() or participant.username} a été retirée.")
        return redirect('dashboard_admin:participants')

    team = get_object_or_404(Team, pk=team_id)
    with transaction.atomic():
        memberships = TeamMembership.objects.filter(user=participant)
        already_in_team = memberships.filter(team=team).exists()
        if not already_in_team and team.memberships.count() >= team.max_members:
            messages.error(request, f"L'équipe {team.name} a atteint sa capacité maximale.")
        else:
            memberships.exclude(team=team).delete()
            TeamMembership.objects.get_or_create(user=participant, team=team)
            messages.success(request, f"{participant.get_full_name() or participant.username} est affecté à {team.name}.")
    return redirect('dashboard_admin:participants')


@require_POST
@role_required('admin', 'organization')
def participant_toggle_active(request, user_id):
    User = get_user_model()
    participant = get_object_or_404(User, pk=user_id, role__in=('student', 'mentor'))
    participant.is_active = not participant.is_active
    participant.save(update_fields=['is_active'])
    state = 'activé' if participant.is_active else 'désactivé'
    messages.success(request, f"Le compte de {participant.get_full_name() or participant.username} a été {state}.")
    return redirect('dashboard_admin:participants')


@require_POST
@role_required('admin', 'organization')
def participants_auto_assign(request):
    active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at').first()
    teams = list(Team.objects.filter(hackathon=active_hackathon).order_by('name')) if active_hackathon else list(Team.objects.order_by('name'))
    if not teams:
        messages.error(request, "Aucune équipe n'est disponible pour l'affectation.")
        return redirect('dashboard_admin:participants')

    User = get_user_model()
    orphaned = list(User.objects.filter(role='student', is_active=True).annotate(
        has_team=Exists(TeamMembership.objects.filter(user_id=OuterRef('pk'))),
    ).filter(has_team=False).order_by('date_joined', 'pk'))
    assigned = 0
    with transaction.atomic():
        counts = {team.pk: team.memberships.count() for team in teams}
        for student in orphaned:
            available = [team for team in teams if counts[team.pk] < team.max_members]
            if not available:
                break
            skill_set = {str(skill).casefold() for skill in (student.skills or [])}

            def score(team):
                requested = team.seeking_skill.casefold().strip()
                match = int(bool(requested) and any(requested in skill or skill in requested for skill in skill_set))
                return match, -(counts[team.pk] / max(team.max_members, 1)), team.name

            selected = max(available, key=score)
            TeamMembership.objects.create(team=selected, user=student)
            counts[selected.pk] += 1
            assigned += 1
    messages.success(request, f'{assigned} participant(s) affecté(s) automatiquement.')
    if assigned < len(orphaned):
        messages.warning(request, f"{len(orphaned) - assigned} participant(s) restent sans équipe faute de places disponibles.")
    return redirect('dashboard_admin:participants')


@require_POST
@role_required('admin', 'organization')
def announcement_delete(request, announcement_id):
    announcement = get_object_or_404(Announcement, pk=announcement_id)
    title = announcement.title
    announcement.delete()
    messages.success(request, f"L'annonce « {title} » a été supprimée.")
    return redirect('dashboard_admin:announcements')


@role_required('admin', 'organization')
def announcement_edit(request, announcement_id):
    announcement = get_object_or_404(Announcement, pk=announcement_id)
    form = AnnouncementForm(request.POST or None, instance=announcement)
    if request.method == 'POST' and form.is_valid():
        was_draft = announcement.is_draft
        was_scheduled = bool(announcement.scheduled_at)
        announcement = form.save(commit=False)
        announcement.is_draft = request.POST.get('submit_action') == 'draft'
        if not announcement.is_draft:
            if announcement.scheduled_at:
                announcement.published_at = announcement.scheduled_at
            elif was_draft or was_scheduled:
                announcement.published_at = timezone.now()
        announcement.save()
        messages.success(request, "L'annonce a été mise à jour.")
        return redirect('dashboard_admin:announcements')
    history_page = Paginator(
        Announcement.objects.select_related('hackathon').annotate(
            effective_at=Coalesce('scheduled_at', 'published_at'),
        ).order_by('-effective_at', '-pk'), 10,
    ).get_page(request.GET.get('page'))
    return render(request, 'dashboard_admin/announcements.html', {
        'form': form,
        'editing_announcement': announcement,
        'active_hackathon': announcement.hackathon,
        'past_announcements': history_page.object_list,
        'page_obj': history_page,
        'announcement_categories': Announcement.objects.exclude(category='').values_list('category', flat=True).distinct().order_by('category'),
        'filter_values': {key: request.GET.get(key, '') for key in ('q', 'category', 'audience', 'priority', 'status', 'date_from', 'date_to')},
        'announcement_stats': {
            'total': Announcement.objects.count(),
            'published': Announcement.objects.filter(is_draft=False).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=timezone.now())).count(),
            'week': Announcement.objects.filter(is_draft=False, published_at__gte=timezone.now() - timedelta(days=7)).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=timezone.now())).count(),
            'urgent': Announcement.objects.filter(is_draft=False, priority=Announcement.Priority.URGENT).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=timezone.now())).count(),
            'scheduled': Announcement.objects.filter(is_draft=False, scheduled_at__gt=timezone.now()).count(),
            'drafts': Announcement.objects.filter(is_draft=True).count(),
        },
    })


def _event_overview_context(form, editing_event=None):
    now = timezone.now()
    events = Hackathon.objects.prefetch_related(
        'milestones', 'registrations__user', 'teams',
    ).order_by('-starts_at')
    rows = []
    for event in events:
        if event.ends_at <= now:
            status, status_color = 'Terminé', 'secondary'
        elif event.starts_at > now:
            status, status_color = 'À venir', 'info'
        elif not event.is_active:
            status, status_color = 'Suspendu', 'warning'
        else:
            status, status_color = 'En cours', 'success'

        registrations = list(event.registrations.all())
        students = sum(registration.user.role == 'student' for registration in registrations)
        mentors = sum(registration.user.role == 'mentor' for registration in registrations)
        milestones = list(event.milestones.all())
        completed_milestones = sum(milestone.status == 'done' for milestone in milestones)
        if milestones:
            progress = round(completed_milestones * 100 / len(milestones))
            progress_detail = f'{completed_milestones}/{len(milestones)} jalons terminés'
        elif event.ends_at <= now:
            progress = 100
            progress_detail = 'Période terminée'
        elif event.starts_at > now:
            progress = 0
            progress_detail = 'Aucun jalon défini'
        else:
            duration = max((event.ends_at - event.starts_at).total_seconds(), 1)
            elapsed = (now - event.starts_at).total_seconds()
            progress = max(0, min(100, round(elapsed * 100 / duration)))
            progress_detail = 'Progression temporelle · aucun jalon défini'

        rows.append({
            'event': event,
            'status': status,
            'status_color': status_color,
            'registrants': len(registrations),
            'students': students,
            'mentors': mentors,
            'teams': event.teams.count(),
            'milestones': len(milestones),
            'completed_milestones': completed_milestones,
            'progress': progress,
            'progress_detail': progress_detail,
        })

    total_milestones = sum(row['milestones'] for row in rows)
    total_completed = sum(row['completed_milestones'] for row in rows)
    return {
        'form': form,
        'editing_event': editing_event,
        'events': rows,
        'events_total': len(rows),
        'active_events': sum(row['status'] == 'En cours' for row in rows),
        'upcoming_events': sum(row['status'] == 'À venir' for row in rows),
        'registrants_total': sum(row['registrants'] for row in rows),
        'teams_total': sum(row['teams'] for row in rows),
        'overall_progress': round(total_completed * 100 / total_milestones) if total_milestones else 0,
        'milestones_total': total_milestones,
        'milestones_completed': total_completed,
    }


@role_required('admin', 'organization')
def events_overview(request):
    form = HackathonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        event = form.save()
        messages.success(request, f"L'événement « {event.name} » a été créé.")
        return redirect('dashboard_admin:events_overview')
    return render(request, 'dashboard_admin/events.html', _event_overview_context(form))


@role_required('admin', 'organization')
def event_edit(request, event_id):
    event = get_object_or_404(Hackathon, pk=event_id)
    form = HackathonForm(request.POST or None, instance=event)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f"L'événement « {event.name} » a été mis à jour.")
        return redirect('dashboard_admin:events_overview')
    return render(request, 'dashboard_admin/events.html', _event_overview_context(form, editing_event=event))
