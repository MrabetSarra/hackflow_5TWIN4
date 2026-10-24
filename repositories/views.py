import json
import shutil
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.html import format_html

from accounts.decorators import role_required
from .forms import BranchForm, CommitForm, RepositoryForm, UploadForm
from .models import MergeRequest, MergeSession, Repository, RepositoryFileComment
from .permissions import get_team_repository, student_team
from .services import git_service
from .services import stack as stack_service
from .services.security import get_staged_upload, remove_stage, stage_uploads, staged_ignored_files, staged_secret_findings


def _display_markdown(source):
    try:
        import bleach
        import markdown
    except ImportError:
        return format_html('<pre class="text-body">{}</pre>', source)
    rendered = markdown.markdown(source, extensions=['fenced_code'])
    allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS) | {
        'p', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'hr', 'br', 'blockquote',
        'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    }
    return bleach.clean(rendered, tags=allowed_tags, attributes={'a': ['href', 'title'], 'code': ['class']}, protocols=['http', 'https', 'mailto'], strip=True)


def _deterministic_merge_summary(repository, source, target):
    """Fallback merge request summary built from the diff, without any content."""
    stat = git_service.diff_stat(repository, source, target)
    files = stat['files']
    parts = [f'This merge request brings the changes of "{source}" into "{target}": '
             f'{len(files)} file(s) changed, {stat["insertions"]} line(s) added and '
             f'{stat["deletions"]} line(s) removed.']
    if files:
        listed = ', '.join(files[:8])
        parts.append(f'Changed areas: {listed}{" and others" if len(files) > 8 else ""}.')
    return ' '.join(parts)


def _deterministic_merge_title(source, target):
    """Fallback commit subject for merging one branch into another."""
    return f'Merge {source} into {target}'[:200]


def _git_error_message(error):
    return str(error)[:300]


def _repository_branch_url(slug, branch):
    query = urlencode({'branch': branch})
    return f"{reverse('repositories:detail', args=[slug])}?{query}"


@role_required('student')
def repository_list(request):
    team = student_team(request.user)
    repositories = Repository.objects.filter(team=team) if team else Repository.objects.none()
    form = RepositoryForm(team=team)
    if request.method == 'POST':
        if not team:
            messages.error(request, 'Join or create a team before creating a repository.')
            return redirect('repositories:list')
        form = RepositoryForm(request.POST, team=team)
        if form.is_valid():
            repository = form.save(commit=False)
            repository.team = team
            repository.created_by = request.user
            repository.default_branch = 'main'
            repository.protected_branches = ['main']
            repository.save()
            try:
                git_service.initialize_repository(repository, request.user)
            except Exception as error:
                repository.delete()
                messages.error(request, f'Could not create the repository: {_git_error_message(error)}')
            else:
                messages.success(request, 'Repository created successfully.')
                return redirect('repositories:detail', slug=repository.slug)
    if request.method == 'POST' and team and form.errors:
        return render(request, 'repositories/create.html', {'team': team, 'form': form})
    return render(request, 'repositories/list.html', {'team': team, 'repositories': repositories, 'form': form})


@role_required('student')
def repository_create(request):
    if request.method == 'POST':
        return repository_list(request)
    team = student_team(request.user)
    if not team:
        messages.error(request, 'Join or create a team before creating a repository.')
        return redirect('repositories:list')
    return render(request, 'repositories/create.html', {'team': team, 'form': RepositoryForm(team=team)})


@role_required('student')
def repository_edit(request, slug):
    team = student_team(request.user)
    if not team:
        from django.http import Http404
        raise Http404
    repository = Repository.objects.filter(team=team, slug=slug).first()
    if not repository:
        from django.http import Http404
        raise Http404

    form = RepositoryForm(request.POST or None, instance=repository, team=team)
    if request.method == 'POST' and form.is_valid():
        updated_repository = form.save(commit=False)
        # Keep the repository path and URLs stable when its display name changes.
        updated_repository.slug = repository.slug
        updated_repository.save()
        messages.success(request, 'Repository updated successfully.')
        return redirect('repositories:list')
    return render(request, 'repositories/edit.html', {
        'team': team,
        'repository': repository,
        'form': form,
    })


@role_required('student')
def repository_delete(request, slug):
    from django.http import Http404

    if request.method != 'POST':
        raise Http404
    team = student_team(request.user)
    if not team:
        raise Http404
    repository = Repository.objects.filter(team=team, slug=slug).first()
    if not repository:
        raise Http404

    # Remove only this repository's bare Git directory, after verifying the
    # resolved target is directly inside the configured team repository folder.
    repository_path = repository.path.resolve()
    expected_parent = (settings.REPOS_ROOT / str(repository.team_id)).resolve()
    if repository_path.parent != expected_parent or repository_path.name != f'{repository.slug}.git':
        messages.error(request, 'The repository files could not be safely located; nothing was deleted.')
        return redirect('repositories:list')
    if repository_path.exists():
        shutil.rmtree(repository_path)
    repository.delete()
    messages.success(request, 'Repository and its stored Git history were deleted.')
    return redirect('repositories:list')


@role_required('student', 'mentor')
def repository_detail(request, slug):
    repository = get_team_repository(request.user, slug)
    file_comment_state = request.session.pop('repository_file_comment_state', {})
    if request.method == 'POST' and request.user.role != 'student':
        from django.http import Http404
        raise Http404
    error = None
    try:
        branches = git_service.branch_details(repository)
    except git_service.GitError as exc:
        branches = []
        error = _git_error_message(exc)
        messages.error(request, 'This repository could not be read. ' + error)
    branch_names = [branch['name'] for branch in branches]
    branch = request.GET.get('branch') or repository.default_branch
    try:
        branch = git_service.validate_branch_name(repository, branch)
        if branch not in branch_names:
            branch = repository.default_branch
    except ValidationError:
        branch = repository.default_branch
    branch_form = BranchForm(initial={'source_branch': branch})
    team = repository.team
    is_captain = team.captain_id == request.user.id
    file_path = request.GET.get('file', '')
    file_source = highlighted_file = readme_html = None
    selected_file = None
    if file_path:
        try:
            file_source, highlighted_file = git_service.read_file(repository, branch, file_path)
            selected_file = file_path
        except (ValidationError, git_service.GitError) as exc:
            error = _git_error_message(exc)
            messages.error(request, error)
    try:
        tree = git_service.file_tree(repository, branch)
        if not file_path:
            for entry in git_service.tree_entries(repository, branch):
                if entry.lower() == 'readme.md':
                    readme_source, _ = git_service.read_file(repository, branch, entry)
                    readme_html = _display_markdown(readme_source)
                    break
    except git_service.GitError as exc:
        tree, error = [], _git_error_message(exc)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_branch':
            branch_form = BranchForm(request.POST)
            if branch_form.is_valid():
                try:
                    git_service.create_branch(repository, branch_form.cleaned_data['name'], branch_form.cleaned_data['source_branch'])
                    from .collaboration import _activity, _notify_team
                    _activity(repository, request.user, 'branch', f'Created branch {branch_form.cleaned_data["name"]}', branch_form.cleaned_data['name'])
                    _notify_team(repository, 'Branch created', f'{request.user.get_full_name() or request.user.username} created {branch_form.cleaned_data["name"]}.', request.path, exclude=request.user)
                    messages.success(request, 'Branch created successfully.')
                    return redirect(_repository_branch_url(slug, branch_form.cleaned_data['name']))
                except (ValidationError, git_service.GitError) as exc:
                    messages.error(request, _git_error_message(exc))
        elif action == 'delete_branch' and is_captain:
            try:
                git_service.delete_branch(repository, request.POST.get('branch', ''))
                messages.success(request, 'Branch deleted successfully.')
                return redirect('repositories:detail', slug=slug)
            except (ValidationError, git_service.GitError) as exc:
                messages.error(request, _git_error_message(exc))
        elif action == 'toggle_protection' and is_captain:
            branch_to_update = request.POST.get('branch', '')
            try:
                branch_to_update = git_service.validate_branch_name(repository, branch_to_update)
                if branch_to_update == repository.default_branch:
                    raise ValidationError('The default branch is always protected.')
                if branch_to_update not in branch_names:
                    raise ValidationError('That branch does not exist.')
                protected = list(repository.protected_branches or [])
                if branch_to_update in protected:
                    protected.remove(branch_to_update)
                    messages.success(request, 'Branch protection removed.')
                else:
                    protected.append(branch_to_update)
                    messages.success(request, 'Branch protection enabled.')
                repository.protected_branches = protected
                repository.save(update_fields=['protected_branches'])
                return redirect(_repository_branch_url(slug, branch_to_update))
            except ValidationError as exc:
                messages.error(request, _git_error_message(exc))
        elif action == 'delete_branch':
            messages.error(request, 'Only the team captain can delete a branch.')
        elif action == 'toggle_protection':
            messages.error(request, 'Only the team captain can change branch protection.')
    return render(request, 'repositories/detail.html', {
        'repository': repository, 'branches': branches, 'branch': branch,
        'tree': tree, 'branch_form': branch_form, 'is_captain': is_captain,
        'selected_file': selected_file, 'file_source': file_source,
        'highlighted_file': highlighted_file, 'readme_html': readme_html,
        'activities': repository.activities.select_related('actor')[:10],
        'file_comments': repository.file_comments.filter(branch=branch, file_path=file_path).select_related('author') if selected_file else [],
        'file_comment_state': file_comment_state if file_comment_state.get('branch') == branch and file_comment_state.get('file_path') == selected_file else {},
        'can_write': request.user.role == 'student',
        'error': error,
    })


@role_required('student')
def repository_push(request, slug):
    repository = get_team_repository(request.user, slug)
    branch = request.GET.get('branch') or request.POST.get('branch') or repository.default_branch
    try:
        branch = git_service.validate_branch_name(repository, branch)
        if not git_service.branch_exists(repository, branch):
            raise ValidationError('Choose an existing branch.')
    except (ValidationError, git_service.GitError) as exc:
        messages.error(request, _git_error_message(exc))
        return redirect('repositories:detail', slug=slug)
    if request.method == 'POST' and request.POST.get('cancel_preview') == '1':
        try:
            remove_stage(get_staged_upload(request.POST.get('stage_token', ''), request.user.pk))
        except ValidationError:
            pass
        return redirect(_repository_branch_url(slug, branch))

    if repository.is_protected(branch):
        messages.error(request, 'This branch is protected. Create a new branch and push your changes there, then use a merge request.')
        return redirect(_repository_branch_url(slug, branch))

    if request.method == 'POST' and request.POST.get('confirm_commit') == '1':
        token = request.POST.get('stage_token', '')
        try:
            stage_dir = get_staged_upload(token, request.user.pk)
            upload_mode = request.POST.get('upload_mode', '')
            secret_findings = staged_secret_findings(stage_dir)
            if upload_mode not in ('keep', 'replace'):
                raise ValidationError('Choose a valid upload mode.')
            form = CommitForm(request.POST, secret_findings=secret_findings)
            if not form.is_valid():
                preview = git_service.compare_upload(repository, branch, stage_dir, upload_mode)
                return render(request, 'repositories/push_preview.html', {
                    'repository': repository, 'branch': branch, 'preview': preview,
                    'stage_token': token, 'upload_mode': upload_mode,
                    'commit_form': form, 'ignored_files': staged_ignored_files(stage_dir), 'secret_findings': secret_findings,
                    'file_count': len((stage_dir / 'manifest.txt').read_text(encoding='utf-8').splitlines()),
                })
            git_service.commit_upload(repository, branch, stage_dir, upload_mode, form.cleaned_data['commit_message'], request.user)
            new_commit = git_service.resolve_branch(repository, branch)
            from .collaboration import _activity, _notify_team
            _activity(repository, request.user, 'push', f'Pushed changes to {branch}', branch, new_commit)
            _notify_team(repository, 'New repository push', f'{request.user.get_full_name() or request.user.username} pushed changes to {branch}.',
                         _repository_branch_url(slug, branch), exclude=request.user)
            remove_stage(stage_dir)
            messages.success(request, 'Your changes were committed successfully.')
            return redirect(_repository_branch_url(slug, branch))
        except (ValidationError, git_service.GitError) as exc:
            messages.error(request, _git_error_message(exc))
            return redirect(_repository_branch_url(slug, branch))

    if request.method == 'POST' and request.POST.get('upload_files') == '1':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                try:
                    relative_paths = json.loads(request.POST.get('upload_paths', '[]'))
                    if not isinstance(relative_paths, list) or len(relative_paths) > settings.REPOSITORY_MAX_FILES:
                        raise ValueError
                except (ValueError, TypeError):
                    form.add_error(None, 'The selected folder paths could not be read. Select the files again.')
                    return render(request, 'repositories/push.html', {'repository': repository, 'branch': branch, 'form': form})
                token, stage_dir, ignored_files, file_count = stage_uploads(form.cleaned_data['upload'], request.user.pk, relative_paths)
                preview = git_service.compare_upload(repository, branch, stage_dir, form.cleaned_data['upload_mode'])
                if not any(preview.values()) and not ignored_files:
                    remove_stage(stage_dir)
                    messages.info(request, 'The upload contains no changes for this branch.')
                    return redirect(_repository_branch_url(slug, branch))
                return render(request, 'repositories/push_preview.html', {
                    'repository': repository, 'branch': branch, 'preview': preview,
                    'stage_token': token, 'upload_mode': form.cleaned_data['upload_mode'],
                    'ignored_files': ignored_files, 'file_count': file_count,
                    'commit_form': CommitForm(secret_findings=staged_secret_findings(stage_dir)),
                    'secret_findings': staged_secret_findings(stage_dir),
                })
            except (ValidationError, git_service.GitError) as exc:
                form.add_error(None, _git_error_message(exc))
    else:
        form = UploadForm(initial={'upload_mode': 'keep'})
    return render(request, 'repositories/push.html', {'repository': repository, 'branch': branch, 'form': form})


@role_required('student', 'mentor')
def repository_download(request, slug):
    repository = get_team_repository(request.user, slug)
    revision = request.GET.get('revision') or request.GET.get('branch') or repository.default_branch
    try:
        content = git_service.archive_stream(repository, revision)
    except (ValidationError, git_service.GitError) as exc:
        messages.error(request, _git_error_message(exc))
        return redirect('repositories:detail', slug=slug)
    filename = f'{repository.slug}-{slugify(revision)[:40] or "version"}.zip'
    response = StreamingHttpResponse(content, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required('mentor')
def mentor_repository_list(request):
    repositories = Repository.objects.filter(team__mentor_requests__mentor=request.user,
        team__mentor_requests__status='accepted').select_related('team').distinct()
    return render(request, 'repositories/mentor_list.html', {'repositories': repositories})


@role_required('student', 'mentor')
def file_comment(request, slug):
    if request.method != 'POST':
        from django.http import Http404
        raise Http404
    repository = get_team_repository(request.user, slug)
    branch, path = request.POST.get('branch', ''), request.POST.get('file_path', '')
    try:
        branch = git_service.validate_branch_name(repository, branch)
        if not git_service.branch_exists(repository, branch):
            raise ValidationError('Choose an existing branch.')
        git_service.read_file(repository, branch, path)
        body = request.POST.get('body', '').strip()
        if not body or len(body) > 3000:
            request.session['repository_file_comment_state'] = {
                'branch': branch, 'file_path': path, 'body': request.POST.get('body', ''),
                'error': 'Comments must be between 1 and 3,000 characters.',
            }
            raise ValidationError('Comments must be between 1 and 3,000 characters.')
        request.session.pop('repository_file_comment_state', None)
        RepositoryFileComment.objects.create(repository=repository, author=request.user, branch=branch, file_path=path, body=body)
        messages.success(request, 'File comment added.')
    except (ValidationError, git_service.GitError) as error:
        if not request.session.get('repository_file_comment_state'):
            request.session['repository_file_comment_state'] = {
                'branch': branch, 'file_path': path, 'body': request.POST.get('body', ''),
                'error': str(error)[:300],
            }
    return redirect(f"{reverse('repositories:detail', args=[slug])}?{urlencode({'branch': branch, 'file': path})}")


@role_required('student', 'mentor')
def ai_suggestion(request, slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Use POST for AI suggestions.'}, status=405)
    repository = get_team_repository(request.user, slug)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        feature = payload.get('feature')
        source = target = ''
        if feature == 'commit_message':
            branch = git_service.validate_branch_name(repository, payload.get('branch', ''))
            if repository.is_protected(branch):
                raise ValidationError('Push the changes to an unprotected branch first.')
            stage_dir = get_staged_upload(payload.get('stage_token', ''), request.user.pk)
            diff = git_service.upload_diff(repository, branch, stage_dir, payload.get('upload_mode', 'keep'))
            # Commit subjects need only the beginning of the diff; keeping this
            # request small helps local models respond within the configured timeout.
            diff = diff[:6000]
            instruction = 'Suggest one concise Git commit message. Return only the message.'
        elif feature in ('mr_summary', 'code_review', 'merge_message'):
            mr = MergeRequest.objects.get(repository=repository, pk=payload.get('merge_request_id')) if payload.get('merge_request_id') else None
            source = mr.source_branch if mr else git_service.validate_branch_name(repository, payload.get('source', ''))
            target = mr.target_branch if mr else git_service.validate_branch_name(repository, payload.get('target', ''))
            if feature == 'mr_summary' and source == target:
                raise ValidationError('Choose two different branches to summarize. The source and target are the same.')
            diff = git_service.compare_revisions(repository, source, target)
            if feature == 'mr_summary' and not diff.strip():
                raise ValidationError(
                    f'No changes found between "{source}" and "{target}". '
                    'Push some commits to the source branch first, then generate a summary.'
                )
            if feature == 'mr_summary':
                # A merge request summary needs only representative changes;
                # large diffs can make a local model appear to hang.
                diff = diff[:6000]
            instruction = ('Write an editable merge request description that summarizes what changed and why it matters. '
                           'Use concise plain-language prose with short headings such as Summary, Changes, and Risks. '
                           'Describe data or configuration changes at a high level; never copy, list, or reproduce '
                           'the DATA content, raw JSON, code, or diff. Do not return a JSON object or a code block. '
                           'Mention affected areas and only risks supported by the diff. If the diff contains data '
                           'records, samples or fixtures, ignore their values entirely and describe the code changes '
                           'instead.'
                           if feature == 'mr_summary' else
                           'Suggest one short merge commit title, ideally "Merge <source> into <target>". '
                           'Return only a single title, with no description, bullets, file list, or explanation.'
                           if feature == 'merge_message' else 'Review this diff for likely bugs, readability issues, and missing tests. Give concise actionable suggestions by file. Do not claim certainty.')
        elif feature == 'safety_scan':
            branch = git_service.validate_branch_name(repository, payload.get('branch', ''))
            stage_dir = get_staged_upload(payload.get('stage_token', ''), request.user.pk)
            diff = git_service.upload_diff(repository, branch, stage_dir, payload.get('upload_mode', 'keep'))
            instruction = 'Check the supplied diff for likely secrets or credentials. Report only file paths and categories, never reproduce any secret. Mention that this is an optional review and may miss issues.'
        elif feature == 'project_description':
            # Describe the snapshot that is staged for the next push.
            stage_dir = get_staged_upload(payload.get('stage_token', ''), request.user.pk)
            manifest_file = stage_dir / 'manifest.txt'
            if not manifest_file.is_file():
                raise ValidationError('No staged files found. Upload your project first.')
            all_paths = [p for p in manifest_file.read_text(encoding='utf-8').splitlines() if p.strip()]
            if not all_paths:
                raise ValidationError('The staged upload is empty.')
            files_root = stage_dir / 'files'

            def read_staged(path):
                file_path = files_root / Path(*path.replace('\\', '/').split('/'))
                if not file_path.is_file():
                    return ''
                try:
                    return file_path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    return ''

            detected = stack_service.detect_stack_from_paths(all_paths, read_staged)
            readme = ''
            for path in sorted(all_paths, key=lambda item: (item.count('/'), len(item))):
                if path.lower().endswith('readme.md'):
                    readme = read_staged(path)[:8000]
                    break
            diff = stack_service.description_source(detected, [], readme)
            instruction = (
                'Describe what this project does, for a hackathon submission: the problem it addresses, '
                'who uses it and what its main features are. Base the description only on the README and '
                'the repository structure provided. Write one single paragraph of at most four sentences '
                'and 120 words, in plain prose. Summarise the features instead of listing them one by one. '
                'Do not name any framework, language, library or tool: the technology stack is written '
                'separately and added automatically. Do not mention file names, folder names or versions. '
                'Do not invent results, numbers or business outcomes. Do not use headings, bullet points, '
                'lists, bold text or markdown. Do not output JSON, code blocks or data values: describe '
                'the project in full sentences.'
            )
        elif feature == 'submission_summary':
            if request.user.role != 'student':
                raise ValidationError('Only students can generate a submission summary.')
            team = student_team(request.user)
            repo = Repository.objects.filter(team=team, pk=payload.get('repository_id')).first() if team else None
            if not repo:
                raise ValidationError('Choose one of your team repositories.')
            branch = git_service.validate_branch_name(repo, payload.get('branch', ''))
            commits = git_service.commit_history(repo, branch, limit=20)
            readme = stack_service.find_readme(repo, branch)
            detected = stack_service.detect_stack(repo, branch)
            diff = stack_service.description_source(detected, commits, readme)
            instruction = (
                'Describe what this project does, for a hackathon submission: the problem it addresses, '
                'who uses it and what its main features are. Base the description only on the README, '
                'the repository structure and the commit messages. Write one single paragraph of at most '
                'four sentences and 120 words, in plain prose. Summarise the features instead of listing '
                'them one by one. Do not name any framework, language, library or tool: the technology '
                'stack is written separately and added automatically. Do not mention file names, folder '
                'names or versions. Do not invent results, numbers or business outcomes. Do not use '
                'headings, bullet points, lists, bold text or markdown. Do not output JSON, code blocks '
                'or data values: describe the project in full sentences.'
            )
        elif feature in ('conflict_explain', 'conflict_suggest'):
            session = MergeSession.objects.select_related('merge_request').get(
                merge_request__repository=repository, merge_request_id=payload.get('merge_request_id'))
            path = payload.get('path', '')
            conflict = session.conflicts.get(path)
            if not conflict or conflict['binary']:
                raise ValidationError('AI conflict suggestions are available for text files only.')
            diff = f"FILE: {path}\nSOURCE VERSION:\n{conflict['source']}\nTARGET VERSION:\n{conflict['target']}\nCONFLICT RESULT:\n{conflict['result']}"
            instruction = ('Explain the changes on both sides and why they conflict. Do not edit the code.'
                           if feature == 'conflict_explain' else 'Return only a JSON object with keys result and explanation. result must be the complete proposed merged file content as a JSON string; explanation must briefly describe the choices. The student will edit and confirm it.')
        else:
            raise ValidationError('Choose a supported AI feature.')
        from .ai import AIUnavailable, contains_raw_data, suggest
        try:
            result = suggest(request.user, feature, diff, instruction)
        except AIUnavailable:
            if feature == 'merge_message':
                result = {'suggestion': _deterministic_merge_title(source, target), 'truncated': False, 'fallback': True}
            elif feature == 'mr_summary':
                result = {
                    'suggestion': _deterministic_merge_summary(repository, source, target),
                    'truncated': True,
                    'fallback': True,
                }
            else:
                raise
        if feature in ('submission_summary', 'project_description'):
            summary = stack_service.clean_summary(result['suggestion'])
            unknown = stack_service.unknown_technologies(summary, detected)
            if unknown:
                names = ', '.join(sorted(unknown))
                retry = suggest(request.user, feature, diff,
                                f'{instruction} Your previous draft mentioned {names}, which this project '
                                'does not use. Never mention them or any other unlisted technology.',
                                count_against_limit=False)
                summary = stack_service.clean_summary(retry['suggestion'])
                unknown = stack_service.unknown_technologies(summary, detected)
            if unknown:
                summary = stack_service.strip_unknown_sentences(summary, unknown)
            stack_line = stack_service.stack_sentence(detected)
            summary = f'{summary}\n\n{stack_line}'.strip() if summary else stack_line
            result['suggestion'] = summary
        elif feature in ('mr_summary', 'code_review', 'merge_message') and contains_raw_data(result['suggestion']):
            # The model answered with raw data or code instead of prose.
            if feature == 'merge_message':
                result['suggestion'] = _deterministic_merge_title(source, target)
                result['fallback'] = True
            else:
                result['suggestion'] = _deterministic_merge_summary(repository, source, target)
        return JsonResponse(result)
    except (ValueError, TypeError, ValidationError) as error:
        return JsonResponse({'error': str(error)[:300]}, status=400)
    except MergeRequest.DoesNotExist:
        return JsonResponse({'error': 'That merge request does not exist.'}, status=404)
    except MergeSession.DoesNotExist:
        return JsonResponse({'error': 'That conflict session does not exist.'}, status=404)
    except git_service.GitError as error:
        return JsonResponse({'error': str(error)[:300]}, status=400)
    except Exception as error:
        from .ai import AIUnavailable
        if isinstance(error, AIUnavailable):
            return JsonResponse({'error': str(error)}, status=503)
        raise
