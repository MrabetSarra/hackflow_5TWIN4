from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _t
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Announcement, Hackathon, MentorRequest, Notification, Submission, Team

from .forms import (EvaluationForm, MentoringSessionForm, RequestFilterForm, ResolveRequestForm, TeamFilterForm,
                    TransferRequestForm, TriageCorrectionForm)
from .models import Criterion, MentorAssignment, MentorEvaluation, MentoringSession, RequestTriage
from .tasks import ensure_triages, retry_triage

# Bloquant d'abord, puis important, puis conseil.
URGENCY_RANK = Case(
    When(urgency=MentorRequest.Urgency.BLOCKING, then=Value(0)),
    When(urgency=MentorRequest.Urgency.IMPORTANT, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)
URGENCY_COLORS = {
    MentorRequest.Urgency.BLOCKING: 'danger',
    MentorRequest.Urgency.IMPORTANT: 'warning',
    MentorRequest.Urgency.NORMAL: 'secondary',
}


def _display_name(user):
    return user.get_full_name() or user.username


def _safe_next(request, default):
    """Redirection interne uniquement (évite les redirections ouvertes)."""
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return reverse(default)


def _notify_request_owner(help_request, title, message, icon):
    Notification.objects.create(user=help_request.student, title=title, message=message[:240], icon=icon,
                                url=reverse('student:mentor_request'))


def _decorate_requests(requests):
    for item in requests:
        item.urgency_color = URGENCY_COLORS.get(item.urgency, 'secondary')
        item.ticket_id = f'#T-{item.pk:03}'
    return requests


def _teams_queryset():
    return Team.objects.filter(is_archived=False).annotate(
        members_total=Count('memberships', distinct=True),
        tasks_total=Count('tasks', distinct=True),
        tasks_done=Count('tasks', filter=Q(tasks__status='done'), distinct=True),
        open_requests=Count('mentor_requests', filter=Q(mentor_requests__status=MentorRequest.Status.PENDING),
                            distinct=True),
    )


def _progress(team):
    return round(team.tasks_done * 100 / team.tasks_total) if team.tasks_total else 0


@role_required('mentor')
def dashboard(request):
    """Tableau de bord du mentor connecté."""
    mentor = request.user
    now = timezone.localtime()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pending = MentorRequest.objects.filter(status=MentorRequest.Status.PENDING)
    urgent_requests = _decorate_requests(list(
        pending.select_related('team').annotate(rank=URGENCY_RANK).order_by('rank', 'created_at')[:3]
    ))
    today_sessions = (MentoringSession.objects
                      .filter(mentor=mentor, starts_at__gte=day_start, starts_at__lt=day_start + timedelta(days=1))
                      .exclude(status=MentoringSession.Status.CANCELLED)
                      .select_related('team'))

    stats = [
        {'label': _t('Équipes suivies'), 'value': MentorAssignment.objects.filter(mentor=mentor).count(),
         'icon': 'bi-people-fill', 'color': 'primary'},
        {'label': _t("Demandes d'aide en attente"), 'value': pending.count(),
         'icon': 'bi-bell-fill', 'color': 'warning'},
        {'label': _t('Tickets en cours (moi)'),
         'value': MentorRequest.objects.filter(mentor=mentor, status=MentorRequest.Status.ACCEPTED).count(),
         'icon': 'bi-headset', 'color': 'success'},
        {'label': _t('Évaluations rédigées'), 'value': MentorEvaluation.objects.filter(mentor=mentor).count(),
         'icon': 'bi-pencil-square', 'color': 'accent'},
    ]
    # Annonces de l'organisation destinées aux mentors (fonctionnalité du module admin).
    hackathon = Hackathon.objects.filter(is_active=True).order_by('-starts_at').first()
    recent_announcements = hackathon.announcements.filter(
        audience__in=(Announcement.Audience.ALL, Announcement.Audience.MENTORS), is_draft=False,
    ).filter(Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=timezone.now())).order_by('-published_at')[:3]         if hackathon else Announcement.objects.none()

    context = {
        'recent_announcements': recent_announcements,
        'stats': stats,
        'pending_count': stats[1]['value'],
        'urgent_requests': urgent_requests,
        'today_sessions': today_sessions,
    }
    return render(request, 'mentor/dashboard.html', context)


@role_required('mentor')
def teams_list(request):
    """Toutes les équipes du hackathon ; le mentor peut suivre celles qu'il accompagne."""
    categories = (Team.objects.filter(is_archived=False).exclude(category='')
                  .order_by('category').values_list('category', flat=True).distinct())
    form = TeamFilterForm(request.GET or None, categories=categories)
    teams = _teams_queryset().annotate(
        is_followed=Exists(MentorAssignment.objects.filter(mentor=request.user, team=OuterRef('pk'))),
    ).order_by('-is_followed', 'name')

    if form.is_valid():
        query = form.cleaned_data['q'].strip()
        if query:
            teams = teams.filter(Q(name__icontains=query) | Q(project_name__icontains=query)
                                 | Q(description__icontains=query) | Q(project_pitch__icontains=query))
        if form.cleaned_data['category']:
            teams = teams.filter(category=form.cleaned_data['category'])
        if form.cleaned_data['mine']:
            teams = teams.filter(is_followed=True)

    page = Paginator(teams, 12).get_page(request.GET.get('page'))
    for team in page:
        team.progress = _progress(team)
    params = request.GET.copy()
    params.pop('page', None)
    context = {
        'form': form,
        'page': page,
        'teams': page.object_list,
        'teams_total': page.paginator.count,
        'query_string': params.urlencode(),
    }
    return render(request, 'mentor/teams_list.html', context)


@role_required('mentor')
def team_detail(request, team_id):
    """Fiche d'une équipe vue par le mentor : membres, avancement, tickets, sessions, soumission."""
    team = get_object_or_404(_teams_queryset().select_related('captain', 'hackathon'), pk=team_id)
    team.progress = _progress(team)
    requests = _decorate_requests(list(team.mentor_requests.select_related('mentor').order_by('-created_at')[:10]))
    context = {
        'team': team,
        'members': team.memberships.select_related('user').order_by('joined_at'),
        'is_followed': MentorAssignment.is_following(request.user, team),
        'followers': MentorAssignment.objects.filter(team=team).select_related('mentor'),
        'requests': requests,
        'sessions': team.mentoring_sessions.filter(mentor=request.user).order_by('-starts_at')[:5],
        'submission': Submission.objects.filter(team=team).select_related('milestone').order_by('-updated_at').first(),
    }
    return render(request, 'mentor/team_detail.html', context)


@role_required('mentor')
@require_POST
def team_follow(request, team_id):
    team = get_object_or_404(Team, pk=team_id, is_archived=False)
    MentorAssignment.follow(request.user, team, MentorAssignment.Source.MENTOR)
    messages.success(request, f'Vous suivez maintenant l’équipe {team.name}.')
    return redirect(_safe_next(request, 'mentor:teams_list'))


@role_required('mentor')
@require_POST
def team_unfollow(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    deleted, _ = MentorAssignment.objects.filter(mentor=request.user, team=team).delete()
    if deleted:
        messages.success(request, f'Vous ne suivez plus l’équipe {team.name}.')
    return redirect(_safe_next(request, 'mentor:teams_list'))

@role_required('mentor')
def help_requests(request):
    """File d'attente des demandes d'aide et tickets du mentor."""
    form = RequestFilterForm(request.GET or None)
    view, urgency = 'pending', ''
    if form.is_valid():
        view = form.cleaned_data['view'] or 'pending'
        urgency = form.cleaned_data['urgency']

    requests = MentorRequest.objects.select_related('team', 'student', 'mentor', 'triage__suggested_mentor')
    if view == 'mine':
        requests = requests.filter(mentor=request.user, status=MentorRequest.Status.ACCEPTED)
    elif view == 'resolved':
        requests = requests.filter(mentor=request.user, status=MentorRequest.Status.RESOLVED)
    else:
        requests = requests.filter(status=MentorRequest.Status.PENDING)
    if urgency:
        requests = requests.filter(urgency=urgency)
    requests = requests.annotate(rank=URGENCY_RANK).order_by('rank', 'created_at')

    page = Paginator(requests, 10).get_page(request.GET.get('page'))
    _decorate_requests(page.object_list)
    ensure_triages(page.object_list)  # analyse IA des tickets ouverts, en arrière-plan
    params = request.GET.copy()
    params.pop('page', None)
    context = {
        'form': form,
        'view': view,
        'correction_form': TriageCorrectionForm(),
        'page': page,
        'requests': page.object_list,
        'resolve_form': ResolveRequestForm(),
        'transfer_form': TransferRequestForm(current_mentor=request.user),
        'query_string': params.urlencode(),
        'counts': {
            'pending': MentorRequest.objects.filter(status=MentorRequest.Status.PENDING).count(),
            'mine': MentorRequest.objects.filter(mentor=request.user, status=MentorRequest.Status.ACCEPTED).count(),
        },
    }
    return render(request, 'mentor/help_requests.html', context)


@role_required('mentor')
@require_POST
def request_take(request, request_id):
    """Prendre en charge un ticket en attente (un seul mentor peut le prendre)."""
    with transaction.atomic():
        help_request = get_object_or_404(MentorRequest.objects.select_for_update(), pk=request_id)
        if help_request.status != MentorRequest.Status.PENDING:
            messages.warning(request, 'Ce ticket a déjà été pris en charge par un autre mentor.')
            return redirect('mentor:help_requests')
        help_request.mentor = request.user
        help_request.status = MentorRequest.Status.ACCEPTED
        help_request.save(update_fields=['mentor', 'status'])
        if help_request.team_id:
            MentorAssignment.follow(request.user, help_request.team, MentorAssignment.Source.AUTO)
    _notify_request_owner(help_request, 'Mentor en route',
                          f'{_display_name(request.user)} a pris en charge votre demande « {help_request.subject} ».',
                          'bi-headset')
    messages.success(request, f'Vous avez pris en charge le ticket #T-{help_request.pk:03}.')
    return redirect(f"{reverse('mentor:help_requests')}?view=mine")


def _visible_requests(request):
    """Tickets dont le mentor peut voir / corriger l'analyse IA : en attente, ou les siens."""
    return MentorRequest.objects.filter(Q(status=MentorRequest.Status.PENDING) | Q(mentor=request.user))


@role_required('mentor')
def triage_status(request):
    """État des analyses IA (JSON) : la page interroge ce point d'accès tant qu'une analyse est en cours."""
    ids = [int(value) for value in request.GET.get('ids', '').split(',') if value.isdigit()][:50]
    triages = (RequestTriage.objects.filter(help_request__in=_visible_requests(request).filter(pk__in=ids))
               .select_related('help_request', 'suggested_mentor'))
    # Page à laquelle revenir après « Corriger » / « Relancer » (jamais l'URL de ce point d'accès JSON).
    next_url = request.GET.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        next_url = reverse('mentor:help_requests')
    payload = {}
    for triage in triages:
        payload[triage.help_request_id] = {
            'status': triage.status,
            'html': render_to_string('mentor/_triage.html', {
                'req': triage.help_request, 'triage': triage, 'correction_form': TriageCorrectionForm(),
                'next_url': next_url,
            }, request=request),
        }
    return JsonResponse({'triages': payload})


@role_required('mentor')
@require_POST
def triage_correct(request, request_id):
    help_request = get_object_or_404(_visible_requests(request), pk=request_id)
    triage = get_object_or_404(RequestTriage, help_request=help_request, status=RequestTriage.Status.DONE)
    form = TriageCorrectionForm(request.POST)
    if form.is_valid():
        triage.corrected_category = form.cleaned_data['category']
        triage.corrected_urgency = form.cleaned_data['urgency']
        triage.corrected_by = request.user
        triage.save(update_fields=['corrected_category', 'corrected_urgency', 'corrected_by', 'updated_at'])
        messages.success(request, 'Merci : votre correction améliore le suivi de la qualité de l’IA.')
    else:
        messages.error(request, 'Correction invalide.')
    return redirect(_safe_next(request, 'mentor:help_requests'))


@role_required('mentor')
@require_POST
def triage_retry(request, request_id):
    help_request = get_object_or_404(_visible_requests(request), pk=request_id)
    triage = get_object_or_404(RequestTriage, help_request=help_request, status=RequestTriage.Status.FAILED)
    retry_triage(triage)
    messages.info(request, 'Analyse IA relancée.')
    return redirect(_safe_next(request, 'mentor:help_requests'))


def _my_open_requests(request):
    """Tickets en cours du mentor connecté : un ticket d'un autre mentor donne un 404 (pas de fuite)."""
    return MentorRequest.objects.filter(mentor=request.user, status=MentorRequest.Status.ACCEPTED)


@role_required('mentor')
@require_POST
def request_resolve(request, request_id):
    get_object_or_404(_my_open_requests(request), pk=request_id)
    form = ResolveRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors['resolution_note'][0])
        return redirect(f"{reverse('mentor:help_requests')}?view=mine")
    with transaction.atomic():
        help_request = get_object_or_404(_my_open_requests(request).select_for_update(), pk=request_id)
        help_request.status = MentorRequest.Status.RESOLVED
        help_request.resolution_note = form.cleaned_data['resolution_note']
        help_request.save(update_fields=['status', 'resolution_note'])
    _notify_request_owner(help_request, 'Demande résolue',
                          f'Votre demande « {help_request.subject} » a été marquée comme résolue.',
                          'bi-check-circle-fill')
    messages.success(request, f'Ticket #T-{help_request.pk:03} résolu.')
    return redirect(f"{reverse('mentor:help_requests')}?view=mine")


@role_required('mentor')
@require_POST
def request_transfer(request, request_id):
    get_object_or_404(_my_open_requests(request), pk=request_id)
    form = TransferRequestForm(request.POST, current_mentor=request.user)
    if not form.is_valid():
        messages.error(request, 'Choisissez un mentor valide pour le transfert.')
        return redirect(f"{reverse('mentor:help_requests')}?view=mine")
    new_mentor = form.cleaned_data['mentor']
    with transaction.atomic():
        help_request = get_object_or_404(_my_open_requests(request).select_for_update(), pk=request_id)
        help_request.mentor = new_mentor
        help_request.save(update_fields=['mentor'])
        if help_request.team_id:
            MentorAssignment.follow(new_mentor, help_request.team, MentorAssignment.Source.AUTO)
    Notification.objects.create(
        user=new_mentor, title='Ticket transféré', icon='bi-arrow-left-right',
        message=f'{_display_name(request.user)} vous a transféré « {help_request.subject} ».'[:240],
        url=f"{reverse('mentor:help_requests')}?view=mine",
    )
    _notify_request_owner(help_request, 'Nouveau mentor',
                          f'Votre demande « {help_request.subject} » est suivie par {_display_name(new_mentor)}.',
                          'bi-arrow-left-right')
    messages.success(request, f'Ticket #T-{help_request.pk:03} transféré à {_display_name(new_mentor)}.')
    return redirect(f"{reverse('mentor:help_requests')}?view=mine")


def _notify_team(team, title, message, icon, url):
    """Notifie tous les membres de l'équipe (modèle Notification du module student)."""
    Notification.objects.bulk_create([
        Notification(user=membership.user, title=title, message=message[:240], icon=icon, url=url)
        for membership in team.memberships.select_related('user')
    ])


# ---------------------------------------------------------------------------
# Étape 3 — Sessions de mentorat
# ---------------------------------------------------------------------------

def _my_sessions(request):
    return MentoringSession.objects.filter(mentor=request.user).select_related('team', 'help_request')


@role_required('mentor')
def sessions_list(request):
    """Sessions du mentor connecté : à venir ou passées / annulées."""
    view = request.GET.get('view') if request.GET.get('view') in ('upcoming', 'past') else 'upcoming'
    now = timezone.now()
    active = (MentoringSession.Status.PLANNED, MentoringSession.Status.CONFIRMED)
    upcoming = _my_sessions(request).filter(ends_at__gte=now, status__in=active)
    sessions = upcoming.order_by('starts_at') if view == 'upcoming' else (
        _my_sessions(request).exclude(pk__in=upcoming.values('pk')).order_by('-starts_at'))
    page = Paginator(sessions, 10).get_page(request.GET.get('page'))
    context = {
        'view': view,
        'page': page,
        'sessions': page.object_list,
        'upcoming_count': upcoming.count(),
        'query_string': f'view={view}',
    }
    return render(request, 'mentor/sessions_list.html', context)


@role_required('mentor')
def session_create(request):
    """Planifier une session ; l'équipe et le ticket peuvent être pré-remplis (?team=…&request=…)."""
    initial = {}
    team_id = request.GET.get('team', '')
    request_id = request.GET.get('request', '')
    if request_id.isdigit():
        help_request = MentorRequest.objects.filter(pk=request_id, mentor=request.user).first()
        if help_request:
            initial.update(help_request=help_request, team=help_request.team, topic=help_request.subject[:180],
                           meeting_url=help_request.meeting_url)
    elif team_id.isdigit():
        initial['team'] = team_id

    form = MentoringSessionForm(request.POST or None, initial=initial, mentor=request.user)
    if request.method == 'POST' and form.is_valid():
        session = form.save()
        MentorAssignment.follow(request.user, session.team, MentorAssignment.Source.AUTO)
        when = timezone.localtime(session.starts_at).strftime('%d/%m à %H:%M')
        _notify_team(session.team, 'Session de mentorat planifiée',
                     f'{_display_name(request.user)} vous propose « {session.topic} » le {when}.',
                     'bi-calendar-event', reverse('student:dashboard'))
        messages.success(request, f'Session planifiée avec {session.team.name}.')
        return redirect('mentor:sessions_list')
    return render(request, 'mentor/session_form.html', {'form': form, 'is_new': True})


@role_required('mentor')
def session_update(request, session_id):
    session = get_object_or_404(_my_sessions(request), pk=session_id)
    form = MentoringSessionForm(request.POST or None, instance=session, mentor=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Session mise à jour.')
        return redirect('mentor:sessions_list')
    return render(request, 'mentor/session_form.html', {'form': form, 'is_new': False, 'session': session})


@role_required('mentor')
@require_POST
def session_cancel(request, session_id):
    session = get_object_or_404(_my_sessions(request), pk=session_id)
    if session.status in (MentoringSession.Status.DONE, MentoringSession.Status.CANCELLED):
        messages.warning(request, 'Cette session est déjà terminée ou annulée.')
        return redirect('mentor:sessions_list')
    session.status = MentoringSession.Status.CANCELLED
    session.save(update_fields=['status', 'updated_at'])
    _notify_team(session.team, 'Session annulée',
                 f'La session « {session.topic} » avec {_display_name(request.user)} est annulée.',
                 'bi-calendar-x', reverse('student:dashboard'))
    messages.success(request, 'Session annulée, l’équipe a été prévenue.')
    return redirect('mentor:sessions_list')


@role_required('mentor')
def session_delete(request, session_id):
    session = get_object_or_404(_my_sessions(request), pk=session_id)
    if request.method == 'POST':
        session.delete()
        messages.success(request, 'Session supprimée.')
        return redirect('mentor:sessions_list')
    return render(request, 'mentor/confirm_delete.html', {
        'object_label': f'la session « {session.topic} » avec {session.team.name}',
        'cancel_url': reverse('mentor:sessions_list'),
    })


# ---------------------------------------------------------------------------
# Étape 4 — Feedback : évaluation multi-critères des soumissions
# ---------------------------------------------------------------------------

EVALUABLE_STATUSES = (Submission.Status.SUBMITTED, Submission.Status.APPROVED, Submission.Status.REVISION)


def _my_evaluations(request):
    return (MentorEvaluation.objects.filter(mentor=request.user)
            .select_related('submission__team', 'submission__milestone')
            .prefetch_related('scores__criterion'))


@role_required('mentor')
def submissions(request):
    """Soumissions de projet à évaluer, avec l'évaluation du mentor connecté (s'il y en a une)."""
    my_eval = MentorEvaluation.objects.filter(mentor=request.user, submission=OuterRef('pk'))
    queryset = (Submission.objects.filter(status__in=EVALUABLE_STATUSES, team__is_archived=False)
                .select_related('team', 'milestone')
                .annotate(my_evaluation_id=my_eval.values('pk')[:1])
                .order_by('-submitted_at', '-updated_at'))
    if request.GET.get('mine') == 'on':
        queryset = queryset.filter(team__mentor_assignments__mentor=request.user)
    page = Paginator(queryset, 15).get_page(request.GET.get('page'))
    evaluations_by_id = {e.pk: e for e in _my_evaluations(request).filter(
        pk__in=[s.my_evaluation_id for s in page.object_list if s.my_evaluation_id])}
    for submission in page.object_list:
        submission.my_evaluation = evaluations_by_id.get(submission.my_evaluation_id)
    context = {
        'page': page,
        'submissions': page.object_list,
        'mine': request.GET.get('mine') == 'on',
        'query_string': 'mine=on' if request.GET.get('mine') == 'on' else '',
    }
    return render(request, 'mentor/submission_list.html', context)


@role_required('mentor')
def evaluations(request):
    """Historique des évaluations rédigées par le mentor connecté."""
    queryset = _my_evaluations(request)
    shared = request.GET.get('shared')
    if shared in ('yes', 'no'):
        queryset = queryset.filter(is_shared=(shared == 'yes'))
    page = Paginator(queryset, 10).get_page(request.GET.get('page'))
    context = {
        'page': page,
        'evaluations': page.object_list,
        'shared': shared,
        'query_string': f'shared={shared}' if shared in ('yes', 'no') else '',
    }
    return render(request, 'mentor/evaluations.html', context)


@role_required('mentor')
def evaluation_create(request, submission_id):
    submission = get_object_or_404(Submission.objects.select_related('team', 'milestone'),
                                   pk=submission_id, status__in=EVALUABLE_STATUSES)
    existing = MentorEvaluation.objects.filter(mentor=request.user, submission=submission).first()
    if existing:
        messages.info(request, 'Vous avez déjà évalué cette soumission : vous pouvez modifier votre évaluation.')
        return redirect('mentor:evaluation_update', evaluation_id=existing.pk)

    criteria = Criterion.for_scope(Criterion.Scope.MENTOR)
    form = EvaluationForm(request.POST or None, criteria=criteria,
                          instance=MentorEvaluation(mentor=request.user, submission=submission))
    if request.method == 'POST' and form.is_valid():
        try:
            evaluation = form.save()
        except IntegrityError:
            # Double envoi du formulaire : l'évaluation existe déjà.
            messages.info(request, 'Cette soumission a déjà été évaluée.')
            return redirect('mentor:evaluations')
        MentorAssignment.follow(request.user, submission.team, MentorAssignment.Source.AUTO)
        messages.success(request, f'Évaluation enregistrée : {evaluation.weighted_total()}/20.')
        return redirect('mentor:evaluation_detail', evaluation_id=evaluation.pk)
    return render(request, 'mentor/evaluation_form.html',
                  {'form': form, 'submission': submission, 'is_new': True})


@role_required('mentor')
def evaluation_detail(request, evaluation_id):
    evaluation = get_object_or_404(_my_evaluations(request), pk=evaluation_id)
    return render(request, 'mentor/evaluation_detail.html', {'evaluation': evaluation})


@role_required('mentor')
def evaluation_update(request, evaluation_id):
    evaluation = get_object_or_404(_my_evaluations(request), pk=evaluation_id)
    criteria = Criterion.for_scope(Criterion.Scope.MENTOR)
    form = EvaluationForm(request.POST or None, criteria=criteria, instance=evaluation)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Évaluation mise à jour : {evaluation.weighted_total()}/20.')
        return redirect('mentor:evaluation_detail', evaluation_id=evaluation.pk)
    return render(request, 'mentor/evaluation_form.html',
                  {'form': form, 'submission': evaluation.submission, 'evaluation': evaluation, 'is_new': False})


@role_required('mentor')
def evaluation_delete(request, evaluation_id):
    evaluation = get_object_or_404(_my_evaluations(request), pk=evaluation_id)
    if request.method == 'POST':
        evaluation.delete()
        messages.success(request, 'Évaluation supprimée.')
        return redirect('mentor:evaluations')
    return render(request, 'mentor/confirm_delete.html', {
        'object_label': f"l'évaluation de {evaluation.team.name} ({evaluation.submission.milestone.title})",
        'cancel_url': reverse('mentor:evaluation_detail', args=[evaluation.pk]),
    })


@role_required('mentor')
@require_POST
def evaluation_share(request, evaluation_id):
    evaluation = get_object_or_404(_my_evaluations(request), pk=evaluation_id)
    if evaluation.is_shared:
        messages.info(request, 'Cette évaluation est déjà partagée avec l’équipe.')
    else:
        evaluation.share()
        _notify_team(evaluation.team, 'Nouveau feedback mentor',
                     f'{_display_name(request.user)} a partagé son évaluation : {evaluation.weighted_total()}/20.',
                     'bi-pencil-square', reverse('student:project_submission'))
        messages.success(request, 'Évaluation partagée avec l’équipe.')
    return redirect('mentor:evaluation_detail', evaluation_id=evaluation.pk)
