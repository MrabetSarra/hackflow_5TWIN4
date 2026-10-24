import json
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from student.models import Notification, TeamMembership

from .models import MergeRequest, MergeRequestComment, MergeSession, RepoActivity, Repository
from .forms import MergeRequestForm
from .permissions import get_team_repository
from .services import git_service


def _highlight_diff(source):
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import DiffLexer
    from django.utils.safestring import mark_safe
    return mark_safe(highlight(source, DiffLexer(), HtmlFormatter(nowrap=True)))


def _diff_files(source):
    if not source:
        return []
    sections = re.split(r'(?=^diff --git )', source, flags=re.MULTILINE)
    if sections and not sections[0].startswith('diff --git'):
        sections = sections[1:] if not sections[0].strip() else sections
    files = []
    for section in sections:
        if not section.strip():
            continue
        match = re.search(r'^diff --git a/(.*?) b/(.*?)$', section, re.MULTILINE)
        path = match.group(2) if match else 'Commit details'
        files.append({'path': path, 'html': _highlight_diff(section)})
    return files


def _can_review(user, repository):
    return user.role == 'student' and TeamMembership.objects.filter(team=repository.team, user=user).exists()


def _can_approve(user, merge_request):
    """Who may approve a merge request.

    The team captain always can, including on a request they opened
    themselves: otherwise a captain whose teammates never review would be
    stuck with a merge request that nobody can approve. Any other author
    needs a peer to review the request on a multi member team.
    """
    if not _can_review(user, merge_request.repository):
        return False
    team = merge_request.repository.team
    is_captain = user.pk == team.captain_id
    if merge_request.author_id == user.pk and not is_captain and team.memberships.count() > 1:
        return False
    return is_captain or merge_request.reviewers.filter(pk=user.pk).exists()


def _notify_team(repository, title, message, url, *, exclude=None):
    member_ids = repository.team.memberships.exclude(user=exclude).values_list('user_id', flat=True) if exclude else repository.team.memberships.values_list('user_id', flat=True)
    Notification.objects.bulk_create([
        Notification(user_id=user_id, title=title, message=message, icon='bi-git', url=url)
        for user_id in member_ids
    ])


def _activity(repository, actor, kind, message, branch='', commit_hash=''):
    return RepoActivity.objects.create(repository=repository, actor=actor, kind=kind, message=message,
                                       branch=branch, commit_hash=commit_hash)


@role_required('student', 'mentor')
@git_service.git_failure_fallback
def history(request, slug):
    repository = get_team_repository(request.user, slug)
    branches = git_service.branch_names(repository)
    branch = request.GET.get('branch', repository.default_branch)
    if branch not in branches:
        branch = repository.default_branch
    paginator = Paginator(range(git_service.commit_count(repository, branch)), 25)
    page = paginator.get_page(request.GET.get('page'))
    page.object_list = git_service.commit_history(repository, branch, skip=page.start_index() - 1, limit=25)
    email_users = {user.email.lower(): user for user in get_user_model().objects.filter(
        email__in=[item['email'] for item in page.object_list if item['email']]).only('email', 'profile_photo', 'first_name', 'last_name', 'username')}
    for item in page.object_list:
        user = email_users.get(item['email'].lower())
        item['avatar'] = user.profile_photo.url if user and user.profile_photo else ''
        item['author_name'] = (user.get_full_name() or user.username) if user else item['author']
    return render(request, 'repositories/history.html', {'repository': repository, 'branch': branch, 'branches': branches, 'page_obj': page})


@role_required('student', 'mentor')
@git_service.git_failure_fallback
def commit_view(request, slug, revision):
    repository = get_team_repository(request.user, slug)
    commit = git_service.commit_detail(repository, revision)
    commit['diff_files'] = _diff_files(commit['diff'])
    return render(request, 'repositories/commit.html', {'repository': repository, 'commit': commit,
                   'branches': git_service.branch_names(repository)})


@role_required('student', 'mentor')
@git_service.git_failure_fallback
def compare(request, slug):
    repository = get_team_repository(request.user, slug)
    branches = git_service.branch_names(repository)
    source, target = request.GET.get('source', ''), request.GET.get('target', '')
    diff = None
    if source and target:
        try:
            diff = git_service.compare_revisions(repository, source, target)
        except ValidationError as error:
            messages.error(request, str(error))
    return render(request, 'repositories/compare.html', {'repository': repository, 'branches': branches,
                   'source': source, 'target': target, 'diff': diff, 'diff_files': _diff_files(diff)})


@role_required('student')
@git_service.git_failure_fallback
def merge_request_list(request, slug):
    repository = get_team_repository(request.user, slug)
    branches = git_service.branch_names(repository)
    # The source selector uses its first branch by default; put the default
    # target branch last so the form starts with a likely feature branch.
    branches.sort(key=lambda branch: branch == repository.default_branch)
    members = repository.team.memberships.select_related('user')
    form = MergeRequestForm(
        request.POST if request.method == 'POST' else None,
        branches=branches,
        members=members,
        initial={
            'source_branch': next((branch for branch in branches if branch != repository.default_branch), ''),
            'target_branch': repository.default_branch,
            'reviewers': [str(repository.team.captain_id)] if repository.team.captain_id != request.user.pk else [],
        },
    )
    if request.method == 'POST':
        if not _can_review(request.user, repository):
            raise Http404
        if form.is_valid():
            title = form.cleaned_data['title'].strip()
            source, target = form.cleaned_data['source_branch'], form.cleaned_data['target_branch']
            description = form.cleaned_data['description'].strip()
            reviewer_ids = [int(item) for item in form.cleaned_data['reviewers']]
            try:
                git_service.validate_branch_name(repository, source)
                git_service.validate_branch_name(repository, target)
            except ValidationError as error:
                form.add_error('source_branch', error)
            else:
                mr = MergeRequest.objects.create(repository=repository, title=title, description=description,
                                                 source_branch=source, target_branch=target, author=request.user)
                if reviewer_ids:
                    mr.reviewers.set(reviewer_ids)
                else:
                    candidates = list(repository.team.memberships.exclude(user=request.user).values_list('user_id', flat=True))
                    if repository.team.captain_id in candidates:
                        mr.reviewers.add(repository.team.captain_id)
                    elif candidates:
                        mr.reviewers.add(candidates[0])
                _activity(repository, request.user, 'merge_request', f'Opened merge request: {title}', source)
                _notify_team(repository, 'New merge request', f'{request.user.get_full_name() or request.user.username} opened {title}.',
                             f'/student/repositories/{slug}/merge-requests/{mr.pk}/', exclude=request.user)
                messages.success(request, 'Merge request created.')
                return redirect('repositories:merge_request', slug=slug, request_id=mr.pk)
    return render(request, 'repositories/merge_requests.html', {'repository': repository, 'branches': branches,
                   'merge_requests': repository.merge_requests.select_related('author').prefetch_related('reviewers').all(),
                   'members': members, 'form': form})


@role_required('student')
@git_service.git_failure_fallback
def merge_request_detail(request, slug, request_id):
    repository = get_team_repository(request.user, slug)
    mr = get_object_or_404(MergeRequest.objects.select_related('author', 'repository').prefetch_related('comments__author', 'reviewers'),
                           repository=repository, pk=request_id)
    comment_state_key = f'merge_request_comment_{mr.pk}'
    comment_state = request.session.pop(comment_state_key, {}) if request.method == 'GET' else {}
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'comment':
            if not _can_review(request.user, repository):
                raise Http404
            body = request.POST.get('body', '').strip()
            if body and len(body) <= 5000:
                request.session.pop(comment_state_key, None)
                MergeRequestComment.objects.create(merge_request=mr, author=request.user, body=body)
                _notify_team(repository, 'Merge request comment', f'{request.user.get_full_name() or request.user.username} commented on {mr.title}.',
                             request.path, exclude=request.user)
            else:
                comment_state = {'body': request.POST.get('body', ''),
                                 'error': 'Comments must be between 1 and 5,000 characters.'}
                request.session[comment_state_key] = comment_state
        elif action in ('approve', 'reject'):
            if not _can_approve(request.user, mr):
                messages.error(request, 'Only the team captain or an assigned reviewer can review this request. Authors cannot approve their own request.')
            elif mr.status in (MergeRequest.Status.MERGED, MergeRequest.Status.CLOSED):
                messages.error(request, 'This merge request is already closed.')
            else:
                mr.status = MergeRequest.Status.APPROVED if action == 'approve' else MergeRequest.Status.REJECTED
                mr.save(update_fields=['status', 'updated_at'])
                mr.reviewers.add(request.user)
                _activity(repository, request.user, f'mr_{action}', f'{action.title()} merge request: {mr.title}', mr.target_branch)
                if mr.author_id:
                    status_label = 'approved' if action == 'approve' else 'rejected'
                    Notification.objects.create(user=mr.author, title=f'Merge request {status_label}',
                        message=f'{request.user.get_full_name() or request.user.username} {status_label} {mr.title}.',
                        icon='bi-git', url=request.path)
        elif action == 'preview_merge' and mr.status == MergeRequest.Status.APPROVED and _can_approve(request.user, mr):
            try:
                preview = git_service.merge_preview(repository, mr.source_branch, mr.target_branch)
                if preview['conflicts']:
                    session, _ = MergeSession.objects.get_or_create(merge_request=mr)
                    session.target_tip, session.source_tip = preview['target_tip'], preview['source_tip']
                    session.conflicts, session.resolved = preview['conflicts'], {}
                    session.save()
                    _activity(repository, request.user, 'merge_conflict', f'Conflicts need resolution for {mr.title}', mr.target_branch)
                    _notify_team(repository, 'Merge conflict needs resolution', f'{mr.title} has conflicts to resolve.',
                                 f'/student/repositories/{slug}/merge-requests/{mr.pk}/resolve/')
                    return redirect('repositories:resolve_conflicts', slug=slug, request_id=mr.pk)
                merge_diff = git_service.compare_revisions(repository, mr.source_branch, mr.target_branch)
                return render(request, 'repositories/merge_confirmation.html', {
                    'repository': repository, 'merge_request': mr, 'diff': merge_diff,
                    'diff_files': _diff_files(merge_diff),
                    'target_tip': preview['target_tip'], 'source_tip': preview['source_tip'],
                    'message': request.POST.get('merge_message') or f'Merge {mr.source_branch} into {mr.target_branch}',
                })
            except (ValidationError, git_service.GitError) as error:
                messages.error(request, str(error)[:300])
        elif action == 'merge' and mr.status == MergeRequest.Status.APPROVED and _can_approve(request.user, mr):
            try:
                preview = git_service.merge_preview(repository, mr.source_branch, mr.target_branch)
                if preview['conflicts']:
                    session, _ = MergeSession.objects.get_or_create(merge_request=mr)
                    session.target_tip, session.source_tip = preview['target_tip'], preview['source_tip']
                    session.conflicts, session.resolved = preview['conflicts'], {}
                    session.save()
                    _activity(repository, request.user, 'merge_conflict', f'Conflicts need resolution for {mr.title}', mr.target_branch)
                    _notify_team(repository, 'Merge conflict needs resolution', f'{mr.title} has conflicts to resolve.',
                                 f'/student/repositories/{slug}/merge-requests/{mr.pk}/resolve/')
                    return redirect('repositories:resolve_conflicts', slug=slug, request_id=mr.pk)
                if request.POST.get('source_tip') and request.POST.get('source_tip') != preview['source_tip'] or request.POST.get('target_tip') and request.POST.get('target_tip') != preview['target_tip']:
                    raise ValidationError('A branch changed after the merge preview. Review the changes again.')
                commit_hash = git_service.merge_branches(repository, mr.source_branch, mr.target_branch,
                    request.POST.get('merge_message') or f'Merge {mr.source_branch} into {mr.target_branch}', request.user,
                    expected_source=preview['source_tip'], expected_target=preview['target_tip'], allow_protected=True)
                mr.status, mr.merged_commit = MergeRequest.Status.MERGED, commit_hash
                mr.save(update_fields=['status', 'merged_commit', 'updated_at'])
                _activity(repository, request.user, 'merge', f'Merged {mr.source_branch} into {mr.target_branch}', mr.target_branch, commit_hash)
                _notify_team(repository, 'Branches merged', f'{mr.title} was merged into {mr.target_branch}.', request.path)
                messages.success(request, 'Merge completed successfully.')
            except (ValidationError, git_service.GitError) as error:
                messages.error(request, str(error)[:300])
        elif action == 'merge':
            messages.error(request, 'This merge request must be approved by the team captain or an assigned reviewer before it can be merged.')
        elif action == 'close' and mr.author_id == request.user.pk and mr.status not in (MergeRequest.Status.MERGED, MergeRequest.Status.CLOSED):
            mr.status = MergeRequest.Status.CLOSED
            mr.save(update_fields=['status', 'updated_at'])
            mr.merge_session.delete() if hasattr(mr, 'merge_session') else None
        return redirect('repositories:merge_request', slug=slug, request_id=mr.pk)
    try:
        diff = git_service.compare_revisions(repository, mr.source_branch, mr.target_branch)
    except ValidationError:
        diff = 'One of the branches no longer exists.'
    return render(request, 'repositories/merge_request.html', {'repository': repository, 'merge_request': mr,
                   'diff': diff, 'diff_files': _diff_files(diff),
                   'can_review': _can_review(request.user, repository), 'can_approve': _can_approve(request.user, mr),
                   'comment_state': comment_state})


@role_required('student')
@git_service.git_failure_fallback
def resolve_conflicts(request, slug, request_id):
    repository = get_team_repository(request.user, slug)
    mr = get_object_or_404(MergeRequest, repository=repository, pk=request_id, status=MergeRequest.Status.APPROVED)
    if not _can_approve(request.user, mr):
        raise Http404
    session = get_object_or_404(MergeSession, merge_request=mr)
    if request.method == 'POST':
        if request.POST.get('action') == 'abort':
            session.delete()
            messages.success(request, 'The in-progress conflict resolution was aborted.')
            return redirect('repositories:merge_request', slug=slug, request_id=mr.pk)
        try:
            resolutions = {}
            for index, (path, conflict) in enumerate(session.conflicts.items()):
                choice = request.POST.get(f'choice_{index}', 'manual')
                if conflict['binary']:
                    if choice == 'source':
                        resolutions[path] = {'side': 'source'} if conflict['source_exists'] else None
                    elif choice == 'target':
                        resolutions[path] = {'side': 'target'} if conflict['target_exists'] else None
                    else:
                        raise ValidationError('Choose the source or target version for each binary conflict.')
                elif choice in ('source', 'target', 'both'):
                    source_value, target_value = conflict['source'], conflict['target']
                    values = source_value if choice == 'source' else target_value if choice == 'target' else target_value.rstrip() + '\n' + source_value
                    resolutions[path] = values
                else:
                    resolutions[path] = request.POST.get(f'result_{index}', '')
            if request.POST.get('action') == 'save':
                session.resolved = resolutions
                session.save(update_fields=['resolved', 'updated_at'])
                messages.success(request, 'Conflict resolutions saved. You can return to this page later.')
            elif request.POST.get('action') == 'finish':
                message = request.POST.get('commit_message', '').strip()
                commit_hash = git_service.finish_conflicted_merge(repository, mr.source_branch, mr.target_branch,
                    session.target_tip, session.source_tip, resolutions, message, request.user, allow_protected=True)
                mr.status, mr.merged_commit = MergeRequest.Status.MERGED, commit_hash
                mr.save(update_fields=['status', 'merged_commit', 'updated_at'])
                session.delete()
                _activity(repository, request.user, 'merge', f'Merged {mr.source_branch} into {mr.target_branch}', mr.target_branch, commit_hash)
                _notify_team(repository, 'Branches merged', f'{mr.title} was merged into {mr.target_branch}.',
                             f'/student/repositories/{slug}/merge-requests/{mr.pk}/')
                messages.success(request, 'Conflict resolution committed and merge completed.')
                return redirect('repositories:merge_request', slug=slug, request_id=mr.pk)
        except (ValidationError, git_service.GitError) as error:
            messages.error(request, str(error)[:300])
    conflict_rows = [(path, {**conflict, 'draft': session.resolved.get(path, conflict.get('result', ''))})
                     for path, conflict in session.conflicts.items()]
    return render(request, 'repositories/resolve_conflicts.html', {'repository': repository, 'merge_request': mr,
                   'session': session, 'conflicts': conflict_rows, 'saved': session.resolved})


@role_required('student')
@git_service.git_failure_fallback
def restore_commit(request, slug, revision):
    if request.method != 'POST':
        raise Http404
    repository = get_team_repository(request.user, slug)
    branch = request.POST.get('branch', '')
    try:
        commit_hash = git_service.restore_commit(repository, branch, revision, request.POST.get('commit_message', ''), request.user)
        _activity(repository, request.user, 'restore', f'Restored {revision[:7]} on {branch}', branch, commit_hash)
        messages.success(request, 'A new commit restored the selected version.')
    except (ValidationError, git_service.GitError) as error:
        messages.error(request, str(error)[:300])
    return redirect('repositories:detail', slug=slug)
