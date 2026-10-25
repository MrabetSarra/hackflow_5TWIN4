import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _t
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Announcement, Hackathon, HackathonRegistration, MentorRequest, Submission, Team, TeamMembership
from career_opportunities.models import ApplicationHistory, CareerApplication
from .forms import AnnouncementForm, HackathonForm
from .copilot import CopilotError, ask_copilot, build_hackathon_snapshot
from .announcement_generator import AnnouncementGenerationError, generate_announcement_draft
from .team_formation import generate_team_plan

@role_required('admin', 'organization')
def dashboard(request):
    facts, active_hackathon = build_hackathon_snapshot()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'ask_copilot':
            question = request.POST.get('question', '').strip()[:1000]
            if not question:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Saisissez une question.'}, status=400)
                messages.error(request, 'Saisissez une question pour le copilote.')
            else:
                try:
                    result = ask_copilot(question, facts)
                    history = request.session.get('admin_copilot_history', [])
                    history.extend([
                        {'role': 'user', 'content': question},
                        {'role': 'assistant', 'content': result['answer'],
                         'announcement_title': result['announcement_title'],
                         'announcement_body': result['announcement_body']},
                    ])
                    request.session['admin_copilot_history'] = history[-20:]
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse(result)
                except CopilotError as exc:
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        history = request.session.get('admin_copilot_history', [])
                        history.extend([
                            {'role': 'user', 'content': question},
                            {'role': 'assistant', 'content': str(exc)},
                        ])
                        request.session['admin_copilot_history'] = history[-20:]
                        return JsonResponse({'error': str(exc)}, status=503)
                    messages.error(request, str(exc))
            return redirect('dashboard_admin:dashboard')
        if action == 'save_announcement':
            title = request.POST.get('announcement_title', '').strip()[:220]
            body = request.POST.get('announcement_body', '').strip()[:5000]
            if not active_hackathon:
                messages.error(request, 'Aucun hackathon actif pour enregistrer cette annonce en brouillon.')
            elif not title or not body:
                messages.error(request, 'Le titre et le contenu du brouillon sont requis.')
            else:
                Announcement.objects.create(
                    hackathon=active_hackathon, title=title, body=body,
                    author=(request.user.get_full_name() or request.user.username)[:120],
                    category='Rappel', audience=Announcement.Audience.ALL,
                    priority=Announcement.Priority.IMPORTANT, is_draft=True,
                )
                messages.success(request, 'Annonce enregistrée comme brouillon. Elle n’a pas été publiée.')
            return redirect('dashboard_admin:dashboard')

    categories = facts['categories_equipes']
    total_category_teams = sum(item['count'] for item in categories) or 1
    challenges_stats = [{**item, 'percent': round(item['count'] * 100 / total_category_teams)} for item in categories]
    placed_pct = round(facts['etudiants_affectes'] * 100 / facts['participants_inscrits']) if facts['participants_inscrits'] else 0
    kpis = [
        {'label': _t('Participants inscrits'), 'value': facts['participants_inscrits'], 'icon': 'bi-people-fill', 'color': 'primary', 'sub': _t('Hackathon data')},
        {'label': _t('Équipes'), 'value': facts['equipes'], 'icon': 'bi-diagram-3-fill', 'color': 'success', 'sub': _t('Teams in database')},
        {'label': _t('Étudiants affectés'), 'value': f"{placed_pct}%", 'icon': 'bi-pie-chart-fill', 'color': 'accent', 'sub': _t('%(count)s without a team') % {'count': facts['etudiants_sans_equipe']}},
        {'label': _t('Demandes mentor ouvertes'), 'value': facts['demandes_mentorat_ouvertes'], 'icon': 'bi-headset', 'color': 'warning', 'sub': _t('%(count)s blocking') % {'count': facts['demandes_bloquantes_ouvertes']}},
    ]
    pending_alerts = []
    if facts['taches_en_retard']:
        pending_alerts.append({'msg': _t('%(count)s unfinished tasks are past their deadline.') % {'count': facts['taches_en_retard']}, 'action': _t('View teams'), 'url': '/cockpit/teams/', 'urgent': True})
    if facts['etudiants_sans_equipe']:
        pending_alerts.append({'msg': _t('%(count)s registered participants do not have a team.') % {'count': facts['etudiants_sans_equipe']}, 'action': _t('View participants'), 'url': '/cockpit/participants/?status=unassigned', 'urgent': False})

    live_activity = []
    team_queryset = Team.objects.filter(hackathon=active_hackathon) if active_hackathon else Team.objects.all()
    for membership in TeamMembership.objects.filter(team__in=team_queryset).select_related('team').order_by('-joined_at')[:3]:
        live_activity.append({'at': membership.joined_at, 'event': _t('A member joined %(team)s') % {'team': membership.team.name}, 'icon': 'bi-people-fill', 'color': 'success'})
    for submission in Submission.objects.filter(team__in=team_queryset).exclude(submitted_at__isnull=True).select_related('team').order_by('-submitted_at')[:3]:
        live_activity.append({'at': submission.submitted_at, 'event': _t('Deliverable received for %(team)s') % {'team': submission.team.name}, 'icon': 'bi-cloud-check-fill', 'color': 'primary'})
    live_activity.sort(key=lambda item: item['at'], reverse=True)
    for activity in live_activity:
        activity['time'] = timezone.localtime(activity['at']).strftime('%d/%m %H:%M')

    context = {
        'active_hackathon': active_hackathon,
        'facts': facts,
        'kpis': kpis,
        'challenges_stats': challenges_stats,
        'live_activity': live_activity[:4],
        'pending_alerts': pending_alerts,
        'copilot_history': request.session.get('admin_copilot_history', []),
    }
    return render(request, 'dashboard_admin/dashboard.html', context)


@role_required('admin', 'organization')
@require_POST
def copilot_ask(request):
    """Return one grounded copilot reply to the admin chat as JSON."""
    question = request.POST.get('question', '').strip()[:1000]
    if not question:
        return JsonResponse({'error': 'Saisissez une question.'}, status=400)

    facts, _ = build_hackathon_snapshot()
    try:
        result = ask_copilot(question, facts)
    except CopilotError as exc:
        history = request.session.get('admin_copilot_history', [])
        history.extend([
            {'role': 'user', 'content': question},
            {'role': 'assistant', 'content': str(exc)},
        ])
        request.session['admin_copilot_history'] = history[-20:]
        request.session.save()
        return JsonResponse({'error': str(exc)}, status=503)

    history = request.session.get('admin_copilot_history', [])
    history.extend([
        {'role': 'user', 'content': question},
        {'role': 'assistant', 'content': result['answer'],
         'announcement_title': result['announcement_title'],
         'announcement_body': result['announcement_body']},
    ])
    request.session['admin_copilot_history'] = history[-20:]
    return JsonResponse(result)


@role_required('admin', 'organization')
@require_POST
def generate_announcement(request):
    """Generate editable announcement copy without publishing or sending it."""
    try:
        result = generate_announcement_draft(
            audience=request.POST.get('audience', '').strip(),
            topic=request.POST.get('topic', ''),
            tone=request.POST.get('tone', 'professionnel'),
            message_type=request.POST.get('message_type', 'annonce'),
        )
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except AnnouncementGenerationError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    return JsonResponse(result)


@role_required('admin', 'organization')
def team_formation(request):
    if request.method == 'POST' and request.POST.get('action') == 'generate':
        plan = generate_team_plan()
        request.session['team_formation_plan'] = plan
        if not plan['assignments']:
            messages.warning(request, 'Aucune affectation proposée : vérifiez les profils sans équipe et les places disponibles.')
        return redirect('dashboard_admin:team_formation')
    if request.method == 'POST' and request.POST.get('action') == 'apply':
        plan = request.session.get('team_formation_plan') or {}
        assignments = plan.get('assignments', [])
        if not assignments:
            messages.error(request, 'Générez un plan avant de le valider.')
            return redirect('dashboard_admin:team_formation')
        User = get_user_model()
        user_ids = [item['student_id'] for item in assignments]
        team_ids = {item['team_id'] for item in assignments}
        with transaction.atomic():
            active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
            team_queryset = Team.objects.filter(hackathon_id=plan.get('hackathon_id')) if plan.get('hackathon_id') else Team.objects.all()
            locked_teams = {team.pk: team for team in team_queryset.select_for_update().filter(pk__in=team_ids)}
            student_queryset = User.objects.select_for_update().filter(pk__in=user_ids, role='student', is_active=True)
            if (active_hackathon.pk if active_hackathon else None) != plan.get('hackathon_id'):
                student_queryset = student_queryset.none()
            elif active_hackathon:
                registered_ids = HackathonRegistration.objects.filter(hackathon=active_hackathon).values('user_id')
                student_queryset = student_queryset.filter(pk__in=registered_ids)
            available_students = set(student_queryset.annotate(
                has_team=Exists(TeamMembership.objects.filter(user_id=OuterRef('pk'))),
            ).filter(has_team=False).values_list('pk', flat=True))
            team_totals = {team_id: team.memberships.count() for team_id, team in locked_teams.items()}
            valid = len(locked_teams) == len(team_ids) and available_students == set(user_ids)
            for assignment in assignments:
                team_id = assignment['team_id']
                if team_id not in team_totals:
                    valid = False
                    break
                team_totals[team_id] += 1
            if any(team_totals[team_id] > locked_teams[team_id].max_members for team_id in team_totals):
                valid = False
            if not valid:
                request.session.pop('team_formation_plan', None)
                messages.error(request, 'Les profils ou places disponibles ont changé. Générez un nouveau plan avant de l’appliquer.')
                return redirect('dashboard_admin:team_formation')
            TeamMembership.objects.bulk_create([
                TeamMembership(team_id=item['team_id'], user_id=item['student_id']) for item in assignments
            ])
        request.session.pop('team_formation_plan', None)
        messages.success(request, f"Composition validée et {len(assignments)} affectation(s) enregistrée(s).")
        return redirect('dashboard_admin:participants')

    plan = request.session.get('team_formation_plan')
    return render(request, 'dashboard_admin/team_formation.html', {'plan': plan})


@role_required('admin', 'organization')
def teams(request):
    active_hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at', '-pk').first()
    hackathons = Hackathon.objects.order_by('-is_active', '-starts_at', 'name')
    selected_hackathon = request.GET.get('hackathon', '').strip()
    if not selected_hackathon:
        selected_hackathon = 'all'
    teams_queryset = Team.objects.select_related('hackathon', 'captain').prefetch_related(
        'memberships__user', 'submissions__milestone', 'mentor_requests__mentor',
    )
    if selected_hackathon == 'all':
        pass
    elif selected_hackathon.isdigit() and hackathons.filter(pk=int(selected_hackathon)).exists():
        teams_queryset = teams_queryset.filter(hackathon_id=int(selected_hackathon))
    elif active_hackathon:
        selected_hackathon = str(active_hackathon.pk)
        teams_queryset = teams_queryset.filter(hackathon=active_hackathon)
    else:
        selected_hackathon = 'all'

    teams_list = []
    for team in teams_queryset.order_by('name'):
        latest_submission = max(team.submissions.all(), key=lambda item: (item.updated_at, item.pk), default=None)
        if not latest_submission:
            submission_status, submission_color = 'Aucun livrable', 'secondary'
        else:
            status_colors = {
                Submission.Status.DRAFT: ('Brouillon', 'warning'),
                Submission.Status.SUBMITTED: ('Soumis', 'primary'),
                Submission.Status.APPROVED: ('Validé', 'success'),
                Submission.Status.REVISION: ('À corriger', 'danger'),
            }
            submission_status, submission_color = status_colors.get(
                latest_submission.status, (latest_submission.get_status_display(), 'secondary'),
            )
        mentor_request = next((item for item in team.mentor_requests.all() if item.mentor_id), None)
        captain = team.captain
        teams_list.append({
            'id': team.pk,
            'name': team.name,
            'hackathon': team.hackathon.name,
            'challenge': team.category or 'Non renseigné',
            'leader': (captain.get_full_name().strip() or captain.username) if captain else 'Non désigné',
            'members_count': len(team.memberships.all()),
            'max_members': team.max_members,
            'table': team.table_number or team.room or '—',
            'mentor': (mentor_request.mentor.get_full_name().strip() or mentor_request.mentor.username) if mentor_request else 'Non assigné',
            'submission_status': submission_status,
            'submission_color': submission_color,
            'submission_id': latest_submission.pk if latest_submission else None,
            'is_reviewable': bool(latest_submission and latest_submission.submitted_at and latest_submission.status in (
                Submission.Status.SUBMITTED, Submission.Status.APPROVED, Submission.Status.REVISION,
            )),
        })

    return render(request, 'dashboard_admin/teams.html', {
        'teams_list': teams_list,
        'teams_count': len(teams_list),
        'hackathons': hackathons,
        'selected_hackathon': selected_hackathon,
        'active_hackathon': active_hackathon,
    })

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
