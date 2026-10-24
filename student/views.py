import json
import logging
import secrets
import smtplib
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import FileResponse, HttpResponseBadRequest, JsonResponse
from django.db import transaction
from django.db.models import Count, Q
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
try:
    from kombu.exceptions import OperationalError as CeleryOperationalError
except ImportError:  # Local eager-mode fallback does not need Celery's broker package.
    class CeleryOperationalError(Exception):
        pass

from accounts.decorators import role_required
from .forms import AITaskJobForm, DirectMessageForm, InvitationForm, MentorRequestForm, ResourceForm, SubmissionForm, TaskForm, TeamForm
from .models import (AITaskJob, Announcement, DirectMessage, Hackathon, MentorRequest, Milestone, Notification, Resource,
                     Sprint, Submission, Task, Team, TeamInvitation, TeamLeaveRequest, TeamMembership)

logger = logging.getLogger(__name__)


def _team_for(user):
    return Team.objects.filter(memberships__user=user, is_archived=False).select_related('hackathon', 'captain').distinct().first()


def _safe_pk(value):
    """Normalize optional numeric IDs from forms/query strings before ORM lookups."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _user_initials(user):
    parts = [part.strip() for part in (user.first_name, user.last_name) if part and part.strip()]
    return ''.join(part[0].upper() for part in parts[:2]) or user.username[:2].upper()


def _ensure_membership(team, user, role=''):
    if team and user:
        TeamMembership.objects.get_or_create(team=team, user=user, defaults={'role': role})


@role_required('student')
def dashboard(request):
    team = _team_for(request.user)
    hackathon = team.hackathon if team else Hackathon.objects.filter(is_active=True).first()
    tasks = team.tasks.all() if team else Task.objects.none()
    total = tasks.count()
    completed = tasks.filter(status=Task.Status.DONE).count()
    progress = round(completed * 100 / total) if total else 0
    milestones = hackathon.milestones.all() if hackathon else Milestone.objects.none()
    now = timezone.now()
    timeline = [{'title': m.title, 'time': m.due_at, 'status': m.status,
                 'icon': 'bi-check-circle-fill' if m.status == 'done' else ('bi-play-circle-fill' if m.status == 'active' else 'bi-clock-fill')}
                for m in milestones]
    deadlines = [{'label': m.title, 'deadline': m.due_at, 'badge': m.due_at.strftime('%A %Hh%M'),
                  'urgent': m.due_at <= now + timedelta(hours=6)} for m in milestones.filter(due_at__gte=now)[:3]]
    resolved = MentorRequest.objects.filter(student=request.user, status=MentorRequest.Status.RESOLVED).count()
    context = {
        'team': team, 'hackathon': hackathon, 'timeline': timeline, 'upcoming_deadlines': deadlines,
        'progress': progress, 'completed_tasks': completed, 'total_tasks': total, 'resolved_requests': resolved,
        'stats': [
            {'label': 'Completed tasks', 'value': f'{completed}/{total}', 'icon': 'bi-check2-square', 'color': 'success'},
            {'label': 'Resolved mentor requests', 'value': resolved, 'icon': 'bi-headset', 'color': 'primary'},
            {'label': 'Open team spots', 'value': f'{team.places_left}' if team else 'Create a team', 'icon': 'bi-person-plus', 'color': 'warning'},
        ],
        'recent_announcements': [{'title': announcement.title, 'author': announcement.author,
                                  'time': announcement.published_at, 'badge': announcement.category}
                                 for announcement in (hackathon.announcements.all()[:3] if hackathon else [])],
    }
    return render(request, 'student/dashboard.html', context)


@role_required('student')
def team_detail(request):
    team = _team_for(request.user)
    create_form = TeamForm()
    team_edit_form = TeamForm(instance=team) if team else TeamForm()
    resource_form = ResourceForm()
    invitation_form = InvitationForm(team=team)
    show_invite_modal = False
    show_create_modal = False
    show_edit_team_modal = False
    show_resource_modal = bool(team and request.GET.get('edit_resource'))
    if show_resource_modal:
        resource_form = ResourceForm(instance=get_object_or_404(
            Resource, team=team, pk=_safe_pk(request.GET.get('edit_resource'))))
    if request.method == 'POST' and request.POST.get('action') == 'create_team' and not team:
        create_form = TeamForm(request.POST)
        hackathon = Hackathon.objects.filter(is_active=True).first()
        if create_form.is_valid() and hackathon:
            with transaction.atomic():
                team = create_form.save(commit=False)
                team.hackathon, team.captain = hackathon, request.user
                team.save()
                _ensure_membership(team, request.user, 'Captain')
            messages.success(request, 'Your team has been created.')
            return redirect('student:team_detail')
        show_create_modal = True
        if not create_form.is_valid():
            messages.error(request, 'Please correct the errors in the team form.')
        elif not hackathon:
            messages.error(request, 'An active hackathon is required before creating a team.')
    if team and request.method == 'POST':
        action = request.POST.get('action')
        captain_actions = {'edit_team', 'remove_member', 'transfer_captain', 'cancel_invitation',
                           'approve_leave_request', 'decline_leave_request'}
        if action in captain_actions and team.captain_id != request.user.pk:
            messages.error(request, 'Only the team captain can manage team members and settings.')
        elif action == 'edit_team':
            team_edit_form = TeamForm(request.POST, instance=team)
            if team_edit_form.is_valid():
                with transaction.atomic():
                    locked_team = Team.objects.select_for_update().get(pk=team.pk, is_archived=False)
                    for field_name in team_edit_form.Meta.fields:
                        setattr(locked_team, field_name, team_edit_form.cleaned_data[field_name])
                    locked_team.save(update_fields=team_edit_form.Meta.fields)
                messages.success(request, 'Team information updated.')
                return redirect('student:team_detail')
            show_edit_team_modal = True
        elif action == 'remove_member':
            membership = TeamMembership.objects.filter(
                team=team, user_id=_safe_pk(request.POST.get('member_id')),
            ).exclude(user_id=team.captain_id).select_related('user').first()
            if membership is None:
                messages.error(request, 'That team member could not be found or cannot be removed.')
            else:
                with transaction.atomic():
                    locked_team = Team.objects.select_for_update().get(pk=team.pk, is_archived=False)
                    membership = TeamMembership.objects.select_for_update().filter(
                        team=locked_team, pk=membership.pk,
                    ).exclude(user_id=locked_team.captain_id).select_related('user').first()
                    if membership is None or locked_team.captain_id != request.user.pk:
                        messages.error(request, 'That team member could not be found or cannot be removed.')
                    else:
                        removed_user = membership.user
                        membership.delete()
                        Notification.objects.create(
                            user=removed_user, title='Removed from team',
                            message=f'You were removed from {locked_team.name}.',
                            icon='bi-person-x-fill', url=reverse('student:team_detail'),
                        )
                        messages.success(request, 'Team member removed.')
                        return redirect('student:team_detail')
        elif action == 'transfer_captain':
            with transaction.atomic():
                locked_team = Team.objects.select_for_update().get(pk=team.pk, is_archived=False)
                next_membership = TeamMembership.objects.select_for_update().filter(
                    team=locked_team, user_id=_safe_pk(request.POST.get('member_id')),
                ).exclude(user_id=request.user.pk).select_related('user').first()
                current_membership = TeamMembership.objects.select_for_update().filter(
                    team=locked_team, user=request.user,
                ).first()
                if locked_team.captain_id != request.user.pk:
                    messages.error(request, 'Only the team captain can transfer captaincy.')
                elif next_membership is None:
                    messages.error(request, 'Choose another member of your team.')
                else:
                    if current_membership and ('captain' in current_membership.role.lower() or 'capitaine' in current_membership.role.lower()):
                        current_membership.role = request.user.specialty or ''
                        current_membership.save(update_fields=['role'])
                    next_membership.role = 'Captain'
                    next_membership.save(update_fields=['role'])
                    locked_team.captain = next_membership.user
                    locked_team.save(update_fields=['captain'])
                    messages.success(request, f'Captaincy transferred to {next_membership.user.get_full_name() or next_membership.user.username}.')
                    return redirect('student:team_detail')
        elif action == 'cancel_invitation':
            invitation = TeamInvitation.objects.filter(
                team=team, pk=_safe_pk(request.POST.get('invitation_id')), status=TeamInvitation.Status.PENDING,
            ).first()
            if invitation is None:
                messages.error(request, 'That pending invitation could not be found.')
            else:
                with transaction.atomic():
                    invitation = TeamInvitation.objects.select_for_update().filter(
                        team=team, pk=invitation.pk, status=TeamInvitation.Status.PENDING,
                    ).first()
                    if invitation:
                        invitation.delete()
                        messages.success(request, 'Pending invitation canceled.')
                        return redirect('student:team_detail')
                messages.error(request, 'That pending invitation could not be found.')
        elif action in {'approve_leave_request', 'decline_leave_request'}:
            with transaction.atomic():
                locked_team = Team.objects.select_for_update().filter(pk=team.pk, is_archived=False).first()
                leave_request = TeamLeaveRequest.objects.select_for_update().filter(
                    team=locked_team, pk=_safe_pk(request.POST.get('leave_request_id')), status=TeamLeaveRequest.Status.PENDING,
                ).select_related('member').first() if locked_team else None
                if not locked_team or locked_team.captain_id != request.user.pk:
                    messages.error(request, 'Only the team captain can decide leave requests.')
                elif leave_request is None:
                    messages.error(request, 'That pending leave request could not be found.')
                elif not TeamMembership.objects.filter(team=locked_team, user=leave_request.member).exists():
                    leave_request.status = TeamLeaveRequest.Status.DECLINED
                    leave_request.decided_by = request.user
                    leave_request.decided_at = timezone.now()
                    leave_request.save(update_fields=['status', 'decided_by', 'decided_at'])
                    messages.error(request, 'The requester is no longer a member of your team.')
                elif action == 'approve_leave_request':
                    TeamMembership.objects.filter(team=locked_team, user=leave_request.member).delete()
                    leave_request.status = TeamLeaveRequest.Status.APPROVED
                    leave_request.decided_by = request.user
                    leave_request.decided_at = timezone.now()
                    leave_request.save(update_fields=['status', 'decided_by', 'decided_at'])
                    Notification.objects.create(
                        user=leave_request.member, title='Team leave request approved',
                        message=f'Your request to leave {locked_team.name} was approved.',
                        icon='bi-box-arrow-right', url=reverse('student:team_detail'),
                    )
                    messages.success(request, 'The member has left the team.')
                    return redirect('student:team_detail')
                else:
                    leave_request.status = TeamLeaveRequest.Status.DECLINED
                    leave_request.decided_by = request.user
                    leave_request.decided_at = timezone.now()
                    leave_request.save(update_fields=['status', 'decided_by', 'decided_at'])
                    Notification.objects.create(
                        user=leave_request.member, title='Team leave request declined',
                        message=f'Your request to leave {locked_team.name} was declined. You remain on the team.',
                        icon='bi-person-check-fill', url=reverse('student:team_detail'),
                    )
                    messages.success(request, 'The leave request was declined. The member remains on the team.')
                    return redirect('student:team_detail')
        elif action == 'leave_team':
            with transaction.atomic():
                locked_team = Team.objects.select_for_update().get(pk=team.pk, is_archived=False)
                membership = TeamMembership.objects.select_for_update().filter(
                    team=locked_team, user=request.user,
                ).first()
                if membership is None:
                    messages.error(request, 'You are no longer a member of this team.')
                elif locked_team.captain_id == request.user.pk and locked_team.memberships.exclude(user=request.user).exists():
                    messages.error(request, 'Transfer captaincy to another member before leaving the team.')
                elif locked_team.captain_id != request.user.pk:
                    leave_request, created = TeamLeaveRequest.objects.get_or_create(
                        team=locked_team, member=request.user, status=TeamLeaveRequest.Status.PENDING,
                    )
                    if created:
                        Notification.objects.create(
                            user=locked_team.captain, title='Team member wants to leave',
                            message=f'{request.user.get_full_name() or request.user.username} asked to leave {locked_team.name}.',
                            icon='bi-box-arrow-left', url=reverse('student:team_detail'),
                        )
                        messages.success(request, 'Your request was sent to the team captain for approval.')
                    else:
                        messages.info(request, 'Your leave request is already waiting for the team captain.')
                    return redirect('student:team_detail')
                else:
                    membership.delete()
                    if locked_team.memberships.count() == 0:
                        locked_team.is_archived = True
                        locked_team.captain = None
                        locked_team.save(update_fields=['is_archived', 'captain'])
                        locked_team.invitations.filter(status=TeamInvitation.Status.PENDING).delete()
                        messages.success(request, 'You left the team. The empty team was archived safely.')
                    else:
                        messages.success(request, 'You left the team.')
                    return redirect('student:team_detail')
        elif action == 'invite':
            if team.captain_id != request.user.id:
                messages.error(request, 'Only the team captain can invite a member.')
            elif team.places_left < 1:
                messages.error(request, 'The team is full.')
            else:
                form = InvitationForm(request.POST, team=team)
                if form.is_valid():
                    invitation = form.save(commit=False)
                    invitation.team, invitation.invited_by = team, request.user
                    invitation.invited_user = getattr(form, 'invited_user', None)
                    invitation.token = secrets.token_urlsafe(24)
                    with transaction.atomic():
                        invitation.save()
                        if invitation.invited_user:
                            Notification.objects.create(user=invitation.invited_user, title='Team invitation',
                                message=f"{team.name} invited you to join their team.", icon='bi-people-fill',
                                url=reverse('student:respond_invitation', args=[invitation.token, 'accept']))
                    invite_path = reverse('student:respond_invitation', args=[invitation.token, 'accept'])
                    try:
                        send_mail('HackFlow team invitation',
                            f"{team.name} invited you to join their HackFlow team. Sign in with this email address and open: {request.build_absolute_uri(invite_path)}",
                            None, [invitation.email], fail_silently=False)
                    except (smtplib.SMTPException, OSError, TimeoutError):
                        logger.warning('Team invitation email delivery failed for invitation id %s', invitation.pk)
                        messages.warning(request, 'The invitation was created, but its email could not be delivered. Share the invitation from your team page.')
                    else:
                        messages.success(request, 'Invitation sent.')
                    return redirect('student:team_detail')
                invitation_form = form
                show_invite_modal = True
        elif request.POST.get('action') in ('resource', 'resource_edit'):
            resource_instance = get_object_or_404(Resource, team=team, pk=_safe_pk(request.POST.get('resource_id'))) if request.POST.get('action') == 'resource_edit' else None
            resource_form = ResourceForm(request.POST, request.FILES, instance=resource_instance)
            if resource_form.is_valid():
                resource = resource_form.save(commit=False)
                resource.team, resource.created_by = team, request.user
                resource.save()
                messages.success(request, 'Team resource saved. Your teammates can see the update now.')
                return redirect('student:team_detail')
            show_resource_modal = True
        elif request.POST.get('action') == 'delete_resource':
            get_object_or_404(Resource, pk=_safe_pk(request.POST.get('resource_id')), team=team).delete()
            messages.success(request, 'Team resource removed.')
            return redirect('student:team_detail')
    if team:
        members = []
        for membership in team.memberships.select_related('user'):
            user = membership.user
            member_role = 'Captain' if membership.role.lower() in ('capitaine', 'captain') else (membership.role or user.specialty)
            members.append({'id': user.pk, 'name': user.get_full_name() or user.username, 'role': member_role,
                            'initials': _user_initials(user),
                            'email': user.email, 'avatar': user.profile_photo.url if user.profile_photo else '',
                            'skills': user.skills, 'is_leader': user.pk == team.captain_id})
        resources = team.resources.select_related('created_by').all()
        repositories = team.repositories.all()
        project_submission = team.submissions.order_by('-updated_at').first()
        project_links = []
        if project_submission:
            submission_editor = (project_submission.submitted_by.get_full_name()
                                 or project_submission.submitted_by.username) if project_submission.submitted_by else 'a team member'
            for title, url, kind in (
                ('GitHub / GitLab Repository', project_submission.github_url, 'github'),
                ('Online Demo', project_submission.demo_url, 'demo'),
                ('Demo Video', project_submission.video_url, 'other'),
            ):
                if url:
                    project_links.append({'title': title, 'url': url, 'kind': kind, 'updated_by': submission_editor})
        team_data = {'name': team.name, 'tagline': team.description, 'category': team.category,
                     'table_number': ' - '.join(filter(None, [team.table_number, team.room])),
                     'member_count': len(members), 'max_members': team.max_members, 'places_left': team.places_left,
                     'members': members, 'seeking_skill': team.seeking_skill, 'resources': resources,
                     'project_links': project_links,
                     'is_captain': team.captain_id == request.user.id,
                     'has_pending_leave_request': TeamLeaveRequest.objects.filter(
                         team=team, member=request.user, status=TeamLeaveRequest.Status.PENDING,
                     ).exists(),
                     'slot_number': team.member_count + 1,
                     'mentor_name': team.mentor_requests.exclude(mentor__isnull=True).select_related('mentor').first().mentor.get_full_name()
                         if team.mentor_requests.exclude(mentor__isnull=True).select_related('mentor').first() else '—',
                     'submission_status': team.submissions.order_by('-updated_at').first().get_status_display()
                         if team.submissions.exists() else 'Draft'}
    else:
        team_data = None
        resources = []
        repositories = []
    return render(request, 'student/team_detail.html', {'team': team_data, 'resources': resources,
                   'can_manage': bool(team and team.captain_id == request.user.id),
                   'can_edit_resources': bool(team), 'create_form': create_form,
                   'show_create_modal': show_create_modal,
                   'team_edit_form': team_edit_form, 'show_edit_team_modal': show_edit_team_modal,
                   'resource_form': resource_form, 'show_resource_modal': show_resource_modal,
                   'invitation_form': invitation_form, 'show_invite_modal': show_invite_modal,
                   'invitation_link': request.build_absolute_uri(reverse('student:respond_invitation', args=[
                       team.invitations.filter(status='pending').order_by('-created_at').first().token, 'accept']))
                       if team and team.invitations.filter(status='pending').exists() else '',
                   'repositories': repositories,
                   'pending_invitations': team.invitations.filter(status=TeamInvitation.Status.PENDING).order_by('-created_at') if team else [],
                   'pending_leave_requests': team.leave_requests.filter(
                       status=TeamLeaveRequest.Status.PENDING,
                   ).select_related('member').order_by('created_at') if team and team.captain_id == request.user.pk else []})


@role_required('student')
def skills_matching(request):
    team = _team_for(request.user)
    available = get_user_model().objects.filter(role='student').exclude(pk=request.user.pk).exclude(team_memberships__isnull=False)
    skill = request.GET.get('skill', '').strip()
    role = request.GET.get('role', '').strip()
    if skill:
        available = available.filter(Q(skills__icontains=skill) | Q(specialty__icontains=skill))
    if role:
        available = available.filter(specialty__icontains=role)
    students = [{'id': u.pk, 'name': u.get_full_name() or u.username, 'school': ' '.join(filter(None, [u.study_level, u.school])),
                 'initials': _user_initials(u), 'avatar': u.profile_photo.url if u.profile_photo else '', 'skills': u.skills, 'bio': u.bio,
                 'preferred_role': u.specialty} for u in available.distinct()]
    available_count = available.count()
    if request.method == 'POST':
        if not team:
            messages.error(request, 'Join a team before inviting a member.')
        elif team.captain_id != request.user.id:
            messages.error(request, 'Only the team captain can add members.')
        elif not team.places_left:
            messages.error(request, 'The team is full.')
        else:
            candidate = get_object_or_404(available, pk=_safe_pk(request.POST.get('user_id')))
            with transaction.atomic():
                invitation, created = TeamInvitation.objects.get_or_create(team=team, invited_user=candidate, status='pending',
                    defaults={'email': candidate.email, 'invited_by': request.user, 'token': secrets.token_urlsafe(24)})
                if created:
                    Notification.objects.create(user=candidate, title='Team invitation',
                        message=f"{team.name} invited you to join their team.",
                        icon='bi-people-fill', url=reverse('student:respond_invitation', args=[invitation.token, 'accept']))
            invited_name = candidate.get_full_name() or candidate.username
            messages.success(request, f'Invitation sent successfully to {invited_name}.')
        return redirect('student:skills_matching')
    teams_qs = Team.objects.filter(is_archived=False).annotate(member_total=Count('memberships')).filter(member_total__lt=models_f('max_members'))
    if team:
        teams_qs = teams_qs.exclude(pk=team.pk)
    teams = [{'name': t.name, 'pitch': t.description, 'category': t.category,
              'cover_img': t.cover_image_url, 'current_members': t.member_total,
              'target_members': t.max_members, 'missing_skills': [t.seeking_skill] if t.seeking_skill else []}
             for t in teams_qs]
    return render(request, 'student/skills_matching.html', {'students_looking': students, 'teams_looking': teams,
                   'team': team, 'available_count': available_count,
                   'can_invite': bool(team and team.captain_id == request.user.id and team.places_left)})


@role_required('student')
def tasks_kanban(request):
    team = _team_for(request.user)
    board_view = 'scrum' if request.GET.get('view') == 'scrum' else 'kanban'
    if not team:
        return render(request, 'student/tasks_kanban.html', {'todo_tasks': [], 'in_progress_tasks': [], 'review_tasks': [], 'done_tasks': [], 'task_form': TaskForm(), 'ai_task_form': AITaskJobForm(), 'board_view': board_view})
    sprint = team.sprints.filter(status=Sprint.Status.ACTIVE).first()
    task_form = TaskForm(team=team)
    ai_task_form = AITaskJobForm(team=team)
    show_create_task_modal = False
    form = None
    editing_task = None
    if board_view == 'scrum' and not sprint:
        now = timezone.now()
        sprint = Sprint.objects.create(team=team, name='Sprint 1', goal=team.project_pitch or team.description,
            starts_at=now, ends_at=team.hackathon.ends_at if team.hackathon.ends_at > now else now + timedelta(days=14))
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_ai_task_job':
            ai_task_form = AITaskJobForm(request.POST, team=team)
            if not ai_task_form.is_valid():
                return JsonResponse({'error': 'Describe a feature in 1,000 characters or fewer.', 'field_errors': ai_task_form.errors}, status=400)
            job = AITaskJob.objects.create(
                team=team, user=request.user, prompt=ai_task_form.cleaned_data['prompt'],
                sprint=ai_task_form.cleaned_data['sprint'],
            )
            try:
                from .tasks import generate_ai_task_job
                generate_ai_task_job.delay(job.pk)
            except (CeleryOperationalError, OSError, ConnectionError, TimeoutError, RuntimeError):
                logger.warning('Could not enqueue AI task job id %s', job.pk)
                job.status = AITaskJob.Status.FAILED
                job.error_message = 'AI task generation could not be queued. Check the worker and broker configuration.'
                job.save(update_fields=['status', 'error_message'])
            return JsonResponse({'job_id': job.pk, 'status': job.status})
        task = Task.objects.filter(team=team, pk=_safe_pk(request.POST.get('task_id'))).first()
        if action in {'create_task_branch', 'status', 'delete', 'edit_task', 'plan_task', 'unplan_task'} and task is None:
            messages.error(request, 'That task could not be found in your team.')
            return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
        if action == 'create_task_branch' and task:
            from repositories.models import Repository
            from repositories.services import git_service
            repository = Repository.objects.filter(team=team, pk=_safe_pk(request.POST.get('repository_id'))).first()
            if not repository:
                messages.error(request, 'Choose one of your team repositories.')
            elif task.repository_branch:
                messages.info(request, 'This task already has a linked branch.')
            else:
                branch_name = f'task-{task.pk}-{slugify(task.title)[:70]}'.strip('-')
                try:
                    git_service.create_branch(repository, branch_name, repository.default_branch)
                    task.repository, task.repository_branch = repository, branch_name
                    task.save(update_fields=['repository', 'repository_branch'])
                    from repositories.collaboration import _activity, _notify_team
                    _activity(repository, request.user, 'task_branch', f'Created task branch for {task.title}', branch_name)
                    _notify_team(repository, 'Task branch created', f'{request.user.get_full_name() or request.user.username} created {branch_name}.',
                                 f'/student/repositories/{repository.slug}/?branch={branch_name}', exclude=request.user)
                    messages.success(request, f'Created branch {branch_name}.')
                except (ValidationError, git_service.GitError) as error:
                    messages.error(request, str(error)[:240])
            return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
        elif action == 'status' and task:
            if request.POST.get('status') in Task.Status.values:
                task.status = request.POST['status']; task.save(update_fields=['status'])
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': True, 'status': task.status, 'status_label': task.get_status_display()})
                return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
        elif action == 'delete' and task:
            task.delete()
            messages.success(request, 'Task deleted.')
            return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
        elif action == 'edit_task' and task:
            form = TaskForm(request.POST, instance=task, team=team)
            if form.is_valid():
                form.save()
                messages.success(request, 'Task updated.')
                return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
            editing_task = task
        elif action == 'plan_task' and task and sprint:
            task.sprint = sprint
            if request.POST.get('status') in Task.Status.values:
                task.status = request.POST['status']
                task.save(update_fields=['sprint', 'status'])
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': True, 'status': task.status, 'status_label': task.get_status_display()})
            else:
                task.save(update_fields=['sprint'])
            messages.success(request, 'Task added to the sprint backlog.')
            return redirect(f"{reverse('student:tasks_kanban')}?view=scrum")
        elif action == 'unplan_task' and task and sprint and task.sprint_id == sprint.pk:
            task.sprint = None; task.save(update_fields=['sprint'])
            messages.success(request, 'Task moved back to the product backlog.')
            return redirect(f"{reverse('student:tasks_kanban')}?view=scrum")
        elif action == 'create':
            form = TaskForm(request.POST, team=team)
            if form.is_valid():
                task = form.save(commit=False); task.team = team; task.save()
                messages.success(request, 'Task added to the board.')
                return redirect(f"{reverse('student:tasks_kanban')}?view=scrum" if board_view == 'scrum' else 'student:tasks_kanban')
            task_form = form
            show_create_task_modal = True
    tasks = team.tasks.select_related('assignee', 'repository').all()
    repositories = team.repositories.all() if team else []
    grouped = {}
    colors = {'Frontend': 'success', 'Backend': 'primary', 'Design & UX': 'info', 'DevOps / Infra': 'secondary', 'Pitch & Slides': 'warning'}
    for status in Task.Status.values:
        grouped[status] = [{'id': t.pk, 'title': t.title, 'description': t.description, 'tag': t.category or 'Project',
                            'tag_color': colors.get(t.category, 'primary'), 'assignee': t.assignee.get_full_name() if t.assignee else 'Unassigned',
                            'urgent': t.priority == Task.Priority.HIGH, 'status': t.status,
                            'repository': t.repository, 'repository_branch': t.repository_branch} for t in tasks.filter(status=status)]
    scrum_groups = {}
    if sprint:
        for status in Task.Status.values:
            scrum_groups[status] = [{'id': t.pk, 'title': t.title, 'description': t.description, 'tag': t.category or 'Project',
                'tag_color': colors.get(t.category, 'primary'), 'assignee': t.assignee.get_full_name() if t.assignee else 'Unassigned',
                'urgent': t.priority == Task.Priority.HIGH, 'status': t.status,
                'repository': t.repository, 'repository_branch': t.repository_branch}
                for t in sprint.tasks.filter(status=status).select_related('assignee')]
    scrum_titles = {
        Task.Status.TODO: ('To do', 'secondary'),
        Task.Status.IN_PROGRESS: ('In progress', 'primary'),
        Task.Status.REVIEW: ('In review / testing', 'warning'),
        Task.Status.DONE: ('Done', 'success'),
    }
    scrum_columns = [{'status': status, 'title': scrum_titles[status][0], 'color': scrum_titles[status][1],
                      'tasks': scrum_groups.get(status, [])} for status in Task.Status.values]
    backlog = []
    for status in Task.Status.values:
        backlog.extend([{'id': t.pk, 'title': t.title, 'category': t.category or 'Project',
                         'assignee': t.assignee.get_full_name() if t.assignee else 'Unassigned',
                         'priority': t.get_priority_display(), 'status': t.get_status_display(),
                         'repository': t.repository, 'repository_branch': t.repository_branch}
                        for t in tasks.filter(sprint__isnull=True, status=status)])
    editing_task = editing_task or Task.objects.filter(team=team, pk=_safe_pk(request.GET.get('edit_task'))).first()
    edit_task_form = form if request.method == 'POST' and request.POST.get('action') == 'edit_task' else TaskForm(instance=editing_task, team=team)
    return render(request, 'student/tasks_kanban.html', {'todo_tasks': grouped['todo'], 'in_progress_tasks': grouped['in_progress'],
                   'review_tasks': grouped['review'], 'done_tasks': grouped['done'], 'task_form': task_form,
                   'show_create_task_modal': show_create_task_modal, 'team': team,
                   'board_view': board_view, 'sprint': sprint, 'scrum_backlog': backlog,
                   'sprint_tasks': scrum_groups, 'scrum_columns': scrum_columns,
                   'sprint_task_count': sprint.tasks.count() if sprint else 0,
                   'editing_task': editing_task, 'edit_task_form': edit_task_form,
                   'repositories': repositories, 'ai_task_form': ai_task_form})


@role_required('student')
def ai_task_job_status(request, job_id):
    team = _team_for(request.user)
    job = get_object_or_404(AITaskJob, team=team, pk=job_id)
    members = TeamMembership.objects.filter(team=team).select_related('user')
    assignees = [{'id': member.user_id, 'name': member.user.get_full_name() or member.user.username}
                 for member in members]
    return JsonResponse({
        'id': job.pk, 'status': job.status, 'error': job.error_message,
        'tasks': job.result if job.status == AITaskJob.Status.DONE else [],
        'assignees': assignees, 'proposed_count': job.proposed_count,
    })


@role_required('student')
def ai_task_job_accept(request, job_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Use POST to add selected tasks.'}, status=405)
    team = _team_for(request.user)
    job = get_object_or_404(AITaskJob, team=team, pk=job_id)
    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'The task selection could not be read.'}, status=400)
    selected = payload.get('tasks') if isinstance(payload, dict) else None
    if not isinstance(selected, list) or not selected or len(selected) > 8:
        return JsonResponse({'error': 'Select between one and eight tasks.'}, status=400)

    with transaction.atomic():
        job = AITaskJob.objects.select_for_update().get(pk=job.pk, team=team)
        if job.status != AITaskJob.Status.DONE:
            return JsonResponse({'error': 'Task suggestions are not ready to add.'}, status=409)
        if job.accepted_task_ids:
            return JsonResponse({'created_count': job.accepted_count, 'task_ids': job.accepted_task_ids, 'already_added': True})
        accepted_ids = []
        accepted_indexes = set()
        valid_member_ids = set(team.memberships.values_list('user_id', flat=True))
        for proposed in selected:
            if not isinstance(proposed, dict):
                return JsonResponse({'error': 'One of the selected tasks is invalid.'}, status=400)
            try:
                proposal_index = int(proposed.get('proposal_index'))
            except (TypeError, ValueError):
                return JsonResponse({'error': 'One of the selected suggestions could not be identified.'}, status=400)
            if proposal_index in accepted_indexes or not 0 <= proposal_index < len(job.result):
                return JsonResponse({'error': 'One of the selected suggestions is invalid.'}, status=400)
            accepted_indexes.add(proposal_index)
            title = proposed.get('title')
            description = proposed.get('description', '')
            category = proposed.get('category', '')
            priority = proposed.get('priority', Task.Priority.NORMAL)
            if not isinstance(title, str) or not title.strip():
                return JsonResponse({'error': 'Every selected task needs a title.'}, status=400)
            if not all(isinstance(value, str) for value in (description, category)):
                return JsonResponse({'error': 'Task descriptions and categories must be text.'}, status=400)
            if priority not in Task.Priority.values:
                return JsonResponse({'error': 'Choose normal or high priority for each task.'}, status=400)
            assignee_id = proposed.get('assignee_id') or proposed.get('suggested_assignee_id') or None
            if assignee_id not in (None, ''):
                try:
                    assignee_id = int(assignee_id)
                except (TypeError, ValueError):
                    return JsonResponse({'error': 'Choose an assignee from your team.'}, status=400)
                if assignee_id not in valid_member_ids:
                    return JsonResponse({'error': 'Choose an assignee from your team.'}, status=400)
            task = Task.objects.create(
                team=team, sprint=job.sprint, title=title.strip()[:180], description=description[:2000],
                category=category[:80], priority=priority, assignee_id=assignee_id,
            )
            accepted_ids.append(task.pk)
        job.accepted_count = len(accepted_ids)
        job.accepted_task_ids = accepted_ids
        job.save(update_fields=['accepted_count', 'accepted_task_ids'])
        messages.success(request, f'{len(accepted_ids)} selected task(s) were added to your team board.')
    return JsonResponse({'created_count': len(accepted_ids), 'task_ids': accepted_ids})


@role_required('student')
def mentor_request(request):
    team = _team_for(request.user)
    editing_request = MentorRequest.objects.filter(
        student=request.user, pk=_safe_pk(request.GET.get('edit')), status=MentorRequest.Status.PENDING,
    ).first() if request.GET.get('edit') else None
    form = MentorRequestForm(instance=editing_request)
    if request.method == 'POST' and request.POST.get('action') in {'update', 'cancel'}:
        item = MentorRequest.objects.filter(
            student=request.user, pk=_safe_pk(request.POST.get('request_id')), status=MentorRequest.Status.PENDING,
        ).first()
        if item is None:
            messages.error(request, 'That pending request could not be found or changed.')
            return redirect('student:mentor_request')
        if request.POST.get('action') == 'cancel':
            with transaction.atomic():
                item.delete()
            messages.success(request, 'Your pending request was canceled.')
            return redirect('student:mentor_request')
        editing_request = item
        form = MentorRequestForm(request.POST, instance=item)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, 'Your request was updated.')
            return redirect('student:mentor_request')
    if request.method == 'POST':
        if request.POST.get('action') not in {'update', 'cancel'} and form.is_valid():
            item = form.save(commit=False); item.student = request.user; item.team = team; item.save()
            messages.success(request, 'Your request has been sent to the mentors.')
            return redirect('student:mentor_request')
    requests = MentorRequest.objects.filter(student=request.user).select_related('mentor')
    today = timezone.localdate()
    is_past_session = lambda request_item: (
        request_item.status == 'resolved'
        or timezone.localtime(request_item.created_at).date() < today
    )
    active = [{'pk': r.pk, 'is_pending': r.status == MentorRequest.Status.PENDING, 'id': f'#T-{r.pk:03}', 'subject': r.subject, 'category': r.category, 'urgency': r.get_urgency_display(),
               'status': r.get_status_display(), 'mentor_name': r.mentor.get_full_name() if r.mentor else '',
               'mentor_initials': _user_initials(r.mentor) if r.mentor else '',
               'mentor_avatar': r.mentor.profile_photo.url if r.mentor and r.mentor.profile_photo else '', 'meeting_url': r.meeting_url,
               'created_at': r.created_at, 'resolution_note': r.resolution_note} for r in requests if not is_past_session(r)]
    past = [{'pk': r.pk, 'is_pending': r.status == MentorRequest.Status.PENDING, 'id': f'#T-{r.pk:03}', 'subject': r.subject, 'category': r.category, 'urgency': r.get_urgency_display(),
             'status': 'Past session' if r.status != 'resolved' else r.get_status_display(), 'mentor_name': r.mentor.get_full_name() if r.mentor else '',
             'mentor_initials': _user_initials(r.mentor) if r.mentor else '',
             'mentor_avatar': r.mentor.profile_photo.url if r.mentor and r.mentor.profile_photo else '',
             'resolution_note': r.resolution_note, 'created_at': r.created_at} for r in requests if is_past_session(r)]
    return render(request, 'student/mentor_request.html', {'active_requests': active, 'past_requests': past,
                   'form': form, 'editing_request': editing_request,
                   'mentor_count': get_user_model().objects.filter(role='mentor').count()})


@role_required('student')
def project_submission(request):
    team = _team_for(request.user)
    hackathon = team.hackathon if team else Hackathon.objects.filter(is_active=True).first()
    milestones = hackathon.milestones.order_by('due_at', 'pk') if hackathon else Milestone.objects.none()
    now = timezone.now()
    default_milestone = milestones.filter(due_at__gte=now).first() or milestones.last()
    selected_milestone_id = request.POST.get('milestone') if request.method == 'POST' else request.GET.get('milestone')
    milestone = milestones.filter(pk=_safe_pk(selected_milestone_id)).first() if selected_milestone_id else default_milestone
    if selected_milestone_id and milestone is None:
        messages.error(request, 'Choose a milestone belonging to your hackathon.')
        milestone = default_milestone
    submission = Submission.objects.filter(team=team, milestone=milestone).first() if team and milestone else None
    now = timezone.now()
    deadline = milestone.due_at if milestone else None
    is_locked = not deadline or deadline <= now
    if request.method == 'POST' and team and milestone:
        if is_locked:
            messages.error(request, 'The project submission deadline has passed. Uploads and changes are closed.')
            form = SubmissionForm(instance=submission, team=team)
        else:
            form = SubmissionForm(request.POST, request.FILES, instance=submission, team=team)
            if form.is_valid():
                if milestone.due_at <= timezone.now():
                    messages.error(request, 'The project submission deadline has passed. Uploads and changes are closed.')
                    form = SubmissionForm(instance=submission, team=team)
                else:
                    repo = form.cleaned_data.get('repository')
                    commit_hash = ''
                    if repo:
                        from repositories.services import git_service
                        try:
                            branch_name = git_service.validate_branch_name(repo, form.cleaned_data['repository_branch'])
                            commit_hash = git_service.resolve_branch(repo, branch_name)
                        except (ValidationError, git_service.GitError) as error:
                            form.add_error('repository_branch', str(error))
                    if not form.errors:
                        item = form.save(commit=False); item.team = team; item.milestone = milestone; item.submitted_by = request.user
                        item.repository = repo
                        item.repository_commit = commit_hash
                        item.status = Submission.Status.SUBMITTED if request.POST.get('action') == 'submit' else Submission.Status.DRAFT
                        if item.status == Submission.Status.SUBMITTED: item.submitted_at = timezone.now()
                        with transaction.atomic():
                            item.save()
                            team.project_name = item.project_name
                            team.project_pitch = item.description
                            team.description = item.description
                            team.category = item.category
                            team.save(update_fields=['project_name', 'project_pitch', 'description', 'category'])
                        messages.success(request, 'Submission saved and shared with your team.')
                        return redirect(f"{reverse('student:project_submission')}?milestone={milestone.pk}")
    elif request.method == 'POST':
        messages.error(request, 'Project submissions are unavailable because there is no active deadline.')
        form = SubmissionForm(instance=submission, team=team)
    else:
        form = SubmissionForm(instance=submission, team=team)
    now = timezone.now()
    is_locked = not deadline or deadline <= now
    context = {'submission': {'status': submission.get_status_display() if submission else 'Draft',
        'deadline': deadline, 'is_locked': is_locked,
        'time_left': deadline if deadline and deadline > now else None,
        'project_name': submission.project_name if submission else (team.project_name if team else ''),
        'short_pitch': submission.description if submission else (team.project_pitch if team else ''),
        'project_summary': submission.project_summary if submission else '',
        'category': submission.category if submission else (team.category if team else ''),
        'github_url': submission.github_url if submission else '', 'demo_url': submission.demo_url if submission else '',
        'repository': submission.repository if submission else None, 'repository_commit': submission.repository_commit if submission else '',
        'video_url': submission.video_url if submission else '',
        'slide_file': submission.file.name if submission and submission.file else '',
        'file_size': submission.file.size if submission and submission.file else None},
        'form': form, 'milestones': milestones, 'selected_milestone': milestone,
        'submission_history': team.submissions.select_related('milestone', 'repository').order_by('-updated_at') if team else [],
        'repositories': team.repositories.all() if team else []}
    return render(request, 'student/project_submission.html', context)


@role_required('admin', 'mentor')
def jury_submissions(request):
    submissions = Submission.objects.exclude(file='').select_related('team', 'milestone').order_by('-submitted_at', '-updated_at')
    template = 'dashboard_admin/submissions.html' if request.user.role == 'admin' else 'mentor/submissions.html'
    return render(request, template, {'submissions': submissions})


@role_required('admin', 'mentor')
def download_submission(request, submission_id):
    submission = get_object_or_404(Submission.objects.select_related('team'), pk=submission_id)
    if not submission.file:
        from django.http import Http404
        raise Http404('This submission does not contain an uploaded file.')
    filename = submission.file.name.rsplit('/', 1)[-1]
    return FileResponse(submission.file.open('rb'), as_attachment=True, filename=filename,
                        content_type='application/zip')


def models_f(name):
    from django.db.models import F
    return F(name)


@role_required('student')
def respond_invitation(request, token, decision):
    invitation = get_object_or_404(TeamInvitation.objects.select_related('team', 'invited_by', 'invited_user'), token=token)
    if invitation.team.is_archived:
        messages.error(request, 'This team is no longer active, so the invitation cannot be accepted.')
        return redirect('student:dashboard')
    if invitation.invited_user_id and invitation.invited_user_id != request.user.id:
        messages.error(request, 'This invitation is not addressed to you.')
        return redirect('student:dashboard')
    if invitation.email.lower() != request.user.email.lower():
        messages.error(request, 'Sign in with the invited email address to respond.')
        return redirect('student:dashboard')
    accept_url = reverse('student:respond_invitation', args=[invitation.token, 'accept'])
    Notification.objects.filter(user=request.user, url=accept_url, is_read=False).update(is_read=True)

    if request.method != 'POST':
        if invitation.status == TeamInvitation.Status.ACCEPTED and TeamMembership.objects.filter(team=invitation.team, user=request.user).exists():
            return redirect('student:team_detail')
        if invitation.status != TeamInvitation.Status.PENDING:
            messages.info(request, 'This invitation has already been answered.')
            return redirect('student:dashboard')
        return render(request, 'student/invitation_response.html', {'invitation': invitation})

    if invitation.status != TeamInvitation.Status.PENDING:
        messages.info(request, 'This invitation has already been answered.')
        return redirect('student:dashboard')

    if decision == 'accept':
        with transaction.atomic():
            locked_team = Team.objects.select_for_update().get(pk=invitation.team_id)
            locked_invitation = TeamInvitation.objects.select_for_update().get(pk=invitation.pk)
            existing_membership = TeamMembership.objects.filter(user=request.user).first()
            if existing_membership and existing_membership.team_id != locked_team.pk:
                messages.error(request, 'You are already a member of another team.')
                return redirect('student:dashboard')
            if not existing_membership and not locked_team.places_left:
                messages.error(request, 'This team is full and can no longer accept the invitation.')
                return redirect('student:dashboard')
            TeamMembership.objects.get_or_create(team=locked_team, user=request.user)
            locked_invitation.invited_user = request.user
            locked_invitation.status = TeamInvitation.Status.ACCEPTED
            locked_invitation.save(update_fields=['invited_user', 'status'])
        Notification.objects.create(
            user=invitation.invited_by, title='Team invitation accepted',
            message=f"{request.user.get_full_name() or request.user.username} joined {invitation.team.name}.",
            icon='bi-person-check-fill', url=reverse('student:team_detail'),
        )
        messages.success(request, f'You joined {invitation.team.name}. Your team workspace is ready.')
        return redirect('student:team_detail')

    if decision == 'decline':
        invitation.invited_user = request.user
        invitation.status = TeamInvitation.Status.DECLINED
        invitation.save(update_fields=['invited_user', 'status'])
        Notification.objects.create(
            user=invitation.invited_by, title='Team invitation declined',
            message=f"{request.user.get_full_name() or request.user.username} declined the invitation to {invitation.team.name}.",
            icon='bi-person-x-fill', url=reverse('student:team_detail'),
        )
        messages.success(request, 'You declined the team invitation.')
        return redirect('student:dashboard')

    return HttpResponseBadRequest('Invalid invitation response.')


@role_required('student')
def message_inbox(request):
    """Show existing conversations and teammates available to contact."""
    User = get_user_model()
    contacts = {}
    history = DirectMessage.objects.filter(Q(sender=request.user) | Q(recipient=request.user)).select_related('sender', 'recipient')
    for item in history:
        contact = item.sender if item.recipient_id == request.user.id else item.recipient
        contacts[contact.pk] = {'user': contact, 'last_message': item}
    team = _team_for(request.user)
    if team:
        for membership in team.memberships.select_related('user').exclude(user=request.user):
            contacts.setdefault(membership.user_id, {'user': membership.user, 'last_message': None})
    conversations = sorted(contacts.values(), key=lambda entry: entry['last_message'].created_at.timestamp() if entry['last_message'] else 0, reverse=True)
    return render(request, 'student/messages.html', {'conversations': conversations})


@role_required('student')
def conversation(request, user_id):
    """Show and continue a conversation between two students."""
    partial = request.GET.get('partial') == '1'
    User = get_user_model()
    other_user = get_object_or_404(User, pk=user_id, role='student')
    if other_user.pk == request.user.pk:
        if partial:
            return HttpResponseBadRequest('A conversation with yourself is not available.')
        messages.error(request, 'You cannot start a conversation with yourself.')
        return redirect('student:messages')

    thread_filter = (Q(sender=request.user, recipient=other_user) |
                     Q(sender=other_user, recipient=request.user))
    thread = DirectMessage.objects.filter(thread_filter).select_related('sender', 'recipient')
    if request.method == 'POST':
        form = DirectMessageForm(request.POST)
        if form.is_valid():
            sent = form.save(commit=False)
            sent.sender, sent.recipient = request.user, other_user
            sent.save()
            Notification.objects.create(
                user=other_user,
                title=f'New message from {request.user.get_full_name() or request.user.username}',
                message=sent.body[:200],
                icon='bi-chat-dots-fill',
                url=reverse('student:conversation', args=[request.user.pk]),
            )
            if not partial:
                return redirect('student:conversation', user_id=other_user.pk)
            form = DirectMessageForm()
    else:
        form = DirectMessageForm()

    thread.filter(sender=other_user, recipient=request.user, is_read=False).update(is_read=True)
    Notification.objects.filter(
        user=request.user,
        url=reverse('student:conversation', args=[other_user.pk]),
        is_read=False,
    ).update(is_read=True)
    context = {
        'other_user': other_user,
        'thread': thread,
        'message_form': form,
    }
    template = 'student/conversation_panel.html' if partial else 'student/conversation.html'
    return render(request, template, context)
