import contextlib
import base64
import difflib
from functools import wraps
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect


class GitError(Exception):
    pass


def git_failure_fallback(view):
    """Turn unexpected Git executable failures into a user-facing response."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except GitError as error:
            message = str(error).strip()[:300] or 'Repository operations are temporarily unavailable.'
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
                return JsonResponse({'error': message}, status=503)
            messages.error(request, message)
            return redirect('repositories:list')
    return wrapped


_thread_locks = {}
_thread_locks_guard = threading.Lock()


def _run(args, *, cwd=None, env=None, check=True, text=True, input=None, timeout=60):
    try:
        result = subprocess.run(
            ['git', *map(str, args)], cwd=cwd, env=env, input=input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            text=text, encoding='utf-8' if text else None, errors='replace' if text else None, shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError('The Git operation timed out. Check GitHub connectivity and try again.') from exc
    except OSError as exc:
        raise GitError('Git could not be started. Check that Git is installed.') from exc
    if check and result.returncode:
        detail = result.stderr.strip() if text else result.stderr.decode(errors='replace').strip()
        raise GitError(detail or 'The Git operation failed.')
    return result


@contextlib.contextmanager
def repository_lock(repository):
    lock_path = settings.REPOS_ROOT / '.locks' / f'{repository.team_id}-{repository.slug}.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve())
    with _thread_locks_guard:
        lock = _thread_locks.setdefault(key, threading.Lock())
    lock.acquire()
    handle = None
    locked = False
    try:
        handle = lock_path.open('a+b')
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if handle:
            if locked and os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif locked:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        lock.release()


def git_env(author=None):
    env = os.environ.copy()
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'})
    env['GIT_CONFIG_GLOBAL'] = os.devnull
    disabled_hooks = Path(settings.BASE_DIR) / 'repositories' / '.hooks-disabled'
    env.update({'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': str(disabled_hooks)})
    token = getattr(settings, 'GITHUB_TOKEN', '')
    if token:
        credential = base64.b64encode(f'x-access-token:{token}'.encode()).decode('ascii')
        env.update({
            'GIT_CONFIG_COUNT': '2',
            'GIT_CONFIG_KEY_1': 'http.https://github.com/.extraheader',
            'GIT_CONFIG_VALUE_1': f'AUTHORIZATION: basic {credential}',
        })
    env.pop('GIT_DIR', None)
    env.pop('GIT_WORK_TREE', None)
    if author:
        name = author.get_full_name().strip() or author.get_username()
        email = author.email.strip() or f'{author.get_username()}@hackflow.local'
        env.update({'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email})
    env.update({'GIT_COMMITTER_NAME': 'HackFlow', 'GIT_COMMITTER_EMAIL': 'hackflow@localhost'})
    return env


def _ensure_remote_cache(repository, *, fetch=True):
    """Hydrate the disposable local bare cache from its GitHub source of truth."""
    if repository.remote_provider != 'github' or not repository.clone_url:
        if settings.DEBUG and repository.path.exists():
            valid = _run(['--git-dir', repository.path, 'rev-parse', '--is-bare-repository'], check=False)
            if valid.returncode == 0 and valid.stdout.strip() == 'true':
                return
        from .github import GitHubError
        try:
            from .github import _configuration
            _configuration()
        except GitHubError as error:
            raise GitError(str(error)) from None
        raise GitError('This repository has no GitHub remote. Run the repository migration command first.')

    if not getattr(settings, 'GITHUB_TOKEN', ''):
        raise GitError('GitHub is not configured. Set GITHUB_TOKEN and GITHUB_OWNER in the server environment.')
    from urllib.parse import urlparse
    remote = urlparse(repository.clone_url)
    if remote.scheme != 'https' or remote.hostname != 'github.com' or not remote.path.endswith('.git'):
        raise GitError('The stored GitHub remote URL is invalid; contact an administrator.')

    path = repository.path
    path.parent.mkdir(parents=True, exist_ok=True)
    env = git_env()
    if not path.exists():
        result = _run(['clone', '--bare', repository.clone_url, path], check=False, env=env)
        if result.returncode:
            try:
                from .github import GitHubError, refresh_repository
                refresh_repository(repository)
            except GitHubError as error:
                raise GitError(str(error)) from None
            _run(['clone', '--bare', repository.clone_url, path], env=env)
    else:
        valid = _run(['--git-dir', path, 'rev-parse', '--is-bare-repository'], check=False)
        if valid.returncode or valid.stdout.strip() != 'true':
            raise GitError('The local repository cache is invalid. It was left untouched; contact an administrator.')
        origin = _run(['--git-dir', path, 'remote', 'get-url', 'origin'], check=False)
        if origin.returncode:
            _run(['--git-dir', path, 'remote', 'add', 'origin', repository.clone_url], env=env)
        else:
            _run(['--git-dir', path, 'remote', 'set-url', 'origin', repository.clone_url], env=env)
        if fetch:
            result = _run([
                '--git-dir', path, 'fetch', '--prune', 'origin',
                '+refs/heads/*:refs/heads/*',
            ], check=False, env=env)
            if result.returncode:
                # Retry once after following a repository rename in GitHub.
                try:
                    from .github import GitHubError, refresh_repository
                    refresh_repository(repository)
                except GitHubError as error:
                    raise GitError(str(error)) from None
                _run(['--git-dir', path, 'remote', 'set-url', 'origin', repository.clone_url], env=env)
                _run(['--git-dir', path, 'fetch', '--prune', 'origin', '+refs/heads/*:refs/heads/*'], env=env)


def _push_branch(repository, branch):
    """Push one validated real branch and report rejection as a failed operation."""
    if settings.DEBUG and repository.remote_provider != 'github':
        return
    _run([
        '--git-dir', repository.path, 'push', 'origin',
        f'refs/heads/{branch}:refs/heads/{branch}',
    ], env=git_env())


def _delete_remote_branch(repository, branch):
    if settings.DEBUG and repository.remote_provider != 'github':
        return
    _run(['--git-dir', repository.path, 'push', 'origin', f':refs/heads/{branch}'], env=git_env())


def initialize_repository(repository, author):
    if repository.remote_provider == 'github':
        _ensure_remote_cache(repository, fetch=False)
        return
    if not settings.DEBUG:
        if repository.path.exists():
            raise GitError(
                'Local Git data already exists for this repository. It was left untouched; '
                'use migrate_local_repositories to transfer its history before linking GitHub.'
            )
        from .github import GitHubError, create_repository
        try:
            create_repository(repository)
            _ensure_remote_cache(repository, fetch=False)
        except GitHubError as error:
            raise GitError(str(error)) from None
        return
    path = repository.path
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hackflow-init-') as working:
        _run(['init', '--initial-branch=main', working])
        _run(['-C', working, 'commit', '--allow-empty', '-m', 'Initialize repository'], env=git_env(author))
        _run(['clone', '--bare', working, path])


def validate_branch_name(repository, name):
    name = (name or '').strip()
    if not name or len(name) > 100:
        raise ValidationError('Enter a valid branch name.')
    result = _run(['check-ref-format', '--branch', name], check=False)
    if result.returncode or result.stdout.strip() != name:
        raise ValidationError('Enter a valid Git branch name.')
    return name


def branch_names(repository):
    _ensure_remote_cache(repository)
    result = _run(['--git-dir', repository.path, 'for-each-ref', '--format=%(refname:short)', 'refs/heads'])
    return [line for line in result.stdout.splitlines() if line]


def branch_details(repository):
    _ensure_remote_cache(repository)
    output = _run([
        '--git-dir', repository.path, 'for-each-ref',
        '--format=%(refname:short)%00%(objectname)%00%(authorname)%00%(authordate:iso8601)%00%(subject)',
        'refs/heads',
    ]).stdout
    branches = []
    for row in output.splitlines():
        parts = row.split('\x00')
        if len(parts) == 5:
            branches.append({'name': parts[0], 'hash': parts[1], 'author': parts[2], 'date': parts[3], 'message': parts[4]})
    return branches


def branch_exists(repository, branch):
    return branch in branch_names(repository)


def resolve_branch(repository, branch):
    _ensure_remote_cache(repository)
    branch = validate_branch_name(repository, branch)
    result = _run(['--git-dir', repository.path, 'rev-parse', '--verify', f'refs/heads/{branch}^{{commit}}'], check=False)
    if result.returncode:
        raise GitError('That branch does not exist.')
    return result.stdout.strip()


def create_branch(repository, name, source):
    name = validate_branch_name(repository, name)
    source = validate_branch_name(repository, source)
    if not branch_exists(repository, source):
        raise ValidationError('Choose an existing source branch.')
    with repository_lock(repository):
        if branch_exists(repository, name):
            raise ValidationError('A branch with this name already exists.')
        _run(['--git-dir', repository.path, 'branch', name, source])
        _push_branch(repository, name)


def delete_branch(repository, name):
    name = validate_branch_name(repository, name)
    if name == repository.default_branch:
        raise ValidationError('The default branch cannot be deleted.')
    with repository_lock(repository):
        _ensure_remote_cache(repository)
        _run(['--git-dir', repository.path, 'branch', '-D', name])
        _delete_remote_branch(repository, name)


@contextlib.contextmanager
def worktree(repository, branch):
    commit = resolve_branch(repository, branch)
    directory = Path(tempfile.mkdtemp(prefix='hackflow-worktree-'))
    try:
        _run(['--git-dir', repository.path, 'worktree', 'add', '--detach', directory, commit], env=git_env())
        yield directory, commit
    finally:
        _run(['--git-dir', repository.path, 'worktree', 'remove', '--force', directory], check=False, env=git_env())
        shutil.rmtree(directory, ignore_errors=True)
        _run(['--git-dir', repository.path, 'worktree', 'prune'], check=False, env=git_env())


def tree_entries(repository, branch):
    commit = resolve_branch(repository, branch)
    output = _run(['--git-dir', repository.path, 'ls-tree', '-r', '-z', '--full-tree', commit], text=False).stdout
    entries = {}
    for row in output.split(b'\0'):
        if not row:
            continue
        metadata, path = row.split(b'\t', 1)
        mode, kind, blob = metadata.decode('ascii').split()
        name = path.decode('utf-8', errors='surrogateescape')
        if mode != '120000' and kind == 'blob':
            entries[name] = blob
    return entries


def file_tree(repository, branch):
    entries = tree_entries(repository, branch)
    root = {'name': '', 'path': '', 'is_dir': True, 'children': []}
    nodes = {'': root}
    for path in sorted(entries):
        parts = path.split('/')
        parent = ''
        for index, part in enumerate(parts):
            current = '/'.join(parts[:index + 1])
            if current not in nodes:
                node = {'name': part, 'path': current, 'is_dir': index < len(parts) - 1, 'children': []}
                nodes[current] = node
                nodes[parent]['children'].append(node)
            parent = current
    return root['children']


def blob_text(repository, blob, limit=200_000):
    """Return the decoded content of a blob already listed by tree_entries."""
    result = _run(['--git-dir', repository.path, 'cat-file', 'blob', blob], text=False)
    return result.stdout[:limit].decode('utf-8', errors='replace')


def read_file(repository, branch, file_path):
    from .security import normalize_repo_path
    safe_path, ignored = normalize_repo_path(file_path)
    if ignored or not safe_path:
        raise ValidationError('This file path is not available.')
    blob = tree_entries(repository, branch).get(safe_path)
    if not blob:
        raise GitError('That file does not exist in this branch.')
    result = _run(['--git-dir', repository.path, 'cat-file', 'blob', blob], text=False)
    content = result.stdout
    if b'\x00' in content:
        raise ValidationError('Binary files cannot be previewed in the browser.')
    try:
        source = content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValidationError('This file cannot be previewed as text.') from exc
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_for_filename
    from pygments.util import ClassNotFound
    try:
        lexer = get_lexer_for_filename(safe_path)
        rendered = highlight(source, lexer, HtmlFormatter(nowrap=True))
    except ClassNotFound:
        rendered = highlight(source, __import__('pygments.lexers', fromlist=['TextLexer']).TextLexer(), HtmlFormatter(nowrap=True))
    return source, rendered


def compare_upload(repository, branch, stage_dir, mode):
    if mode not in ('keep', 'replace'):
        raise ValidationError('Choose a valid upload mode.')
    current = tree_entries(repository, branch)
    manifest = (stage_dir / 'manifest.txt').read_text(encoding='utf-8').splitlines()
    uploaded = {path: stage_dir / 'files' / Path(*path.split('/')) for path in manifest if path}
    additions, modifications, deletions = [], [], []
    for path, file_path in uploaded.items():
        data = file_path.read_bytes()
        if path not in current:
            additions.append(path)
        else:
            existing = _run(['--git-dir', repository.path, 'cat-file', 'blob', current[path]], text=False).stdout
            if existing != data:
                modifications.append(path)
    if mode == 'replace':
        deletions = sorted(set(current) - set(uploaded))
    return {'added': additions, 'modified': modifications, 'deleted': deletions}


def upload_diff(repository, branch, stage_dir, mode):
    preview = compare_upload(repository, branch, stage_dir, mode)
    current = tree_entries(repository, branch)
    selected = preview['added'] + preview['modified'] + preview['deleted']
    sections = []
    for path in selected[:100]:
        old = ''
        if path in current:
            old = _run(['--git-dir', repository.path, 'cat-file', 'blob', current[path]], text=False).stdout.decode('utf-8', errors='replace')
        staged = stage_dir / 'files' / Path(*path.split('/'))
        new = staged.read_bytes().decode('utf-8', errors='replace') if staged.is_file() else ''
        diff = difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=f'a/{path}', tofile=f'b/{path}', lineterm='')
        sections.append('\n'.join(diff))
    return '\n'.join(section for section in sections if section)


def commit_upload(repository, branch, stage_dir, mode, message, author, *, allow_protected=False):
    branch = validate_branch_name(repository, branch)
    if mode not in ('keep', 'replace'):
        raise ValidationError('Choose a valid upload mode.')
    if repository.is_protected(branch) and not allow_protected:
        raise ValidationError('This branch is protected. Push your changes to another branch and use a merge request.')
    message = ' '.join((message or '').replace('\x00', '').split()).strip()
    if not message or len(message) > 200:
        raise ValidationError('Enter a commit message between 1 and 200 characters.')
    _ensure_remote_cache(repository)
    manifest = (stage_dir / 'manifest.txt').read_text(encoding='utf-8').splitlines()
    uploaded = {path: stage_dir / 'files' / Path(*path.split('/')) for path in manifest if path}
    with repository_lock(repository):
        with worktree(repository, branch) as (directory, old_commit):
            if mode == 'replace':
                for path in directory.rglob('*'):
                    relative = path.relative_to(directory)
                    if relative.parts and relative.parts[0] == '.git':
                        continue
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                for path in sorted(directory.rglob('*'), key=lambda item: len(item.parts), reverse=True):
                    relative = path.relative_to(directory)
                    if relative.parts and relative.parts[0] == '.git':
                        continue
                    if path.is_dir():
                        try:
                            path.rmdir()
                        except OSError:
                            pass
            for relative, source in uploaded.items():
                target = directory / Path(*relative.split('/'))
                cursor = directory
                for part in relative.split('/')[:-1]:
                    cursor = cursor / part
                    if cursor.is_symlink():
                        raise ValidationError('Files cannot be written through symbolic links.')
                    if cursor.exists() and not cursor.is_dir():
                        raise ValidationError('A file in this path already blocks the upload.')
                if target.is_symlink():
                    raise ValidationError('Symbolic links cannot be replaced by an upload.')
                if target.exists() and target.is_dir():
                    raise ValidationError('A folder already exists at this file path.')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            # Force-add the snapshot. The upload filter is the single source of
            # truth, so a .gitignore file inside the uploaded project must not
            # silently drop files that the review step already showed.
            _run(['add', '--all', '--force', '--', '.'], cwd=directory, env=git_env())
            diff_result = _run(['diff', '--cached', '--quiet'], cwd=directory, check=False, env=git_env())
            if diff_result.returncode not in (0, 1):
                raise GitError(diff_result.stderr.strip() or 'The staged changes could not be checked.')
            changed = diff_result.returncode == 1
            if not changed:
                raise ValidationError('There are no changes to commit.')
            _run(['commit', '-m', message], cwd=directory, env=git_env(author))
            new_commit = _run(['rev-parse', 'HEAD'], cwd=directory).stdout.strip()
            _run(['--git-dir', repository.path, 'update-ref', f'refs/heads/{branch}', new_commit, old_commit])
            _push_branch(repository, branch)
    return new_commit


def archive_stream(repository, revision):
    if revision in branch_names(repository):
        commit = resolve_branch(repository, revision)
    elif isinstance(revision, str) and len(revision) in range(7, 41) and all(char in '0123456789abcdefABCDEF' for char in revision):
        commit = revision
    else:
        raise ValidationError('Choose a valid branch or commit hash.')
    verify = _run(['--git-dir', repository.path, 'rev-parse', '--verify', f'{commit}^{{commit}}'], check=False)
    if verify.returncode:
        raise GitError('That repository version does not exist.')
    try:
        process = subprocess.Popen(
            ['git', '--git-dir', str(repository.path), 'archive', '--format=zip', verify.stdout.strip()],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, env=git_env(),
        )
    except OSError as exc:
        raise GitError('Git could not be started. Check that Git is installed.') from exc
    def chunks():
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
            error = process.stderr.read().decode(errors='replace')
            if process.wait() and error:
                raise GitError('The repository archive could not be created.')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
    return chunks()


def commit_history(repository, branch, *, skip=0, limit=25):
    branch = validate_branch_name(repository, branch)
    if not branch_exists(repository, branch):
        raise ValidationError('Choose an existing branch.')
    output = _run(['--git-dir', repository.path, 'log', branch, f'--skip={skip}', f'-{limit}',
                   '--format=%H%x00%h%x00%an%x00%ae%x00%aI%x00%s']).stdout
    rows = []
    for line in output.splitlines():
        parts = line.split('\x00', 5)
        if len(parts) == 6:
            rows.append(dict(zip(('hash', 'short_hash', 'author', 'email', 'date', 'message'), parts)))
    return rows


def commit_count(repository, branch):
    _ensure_remote_cache(repository)
    branch = validate_branch_name(repository, branch)
    result = _run(['--git-dir', repository.path, 'rev-list', '--count', branch], check=False)
    return int(result.stdout.strip()) if result.returncode == 0 else 0


def commit_detail(repository, revision):
    commit = _resolve_commit(repository, revision)
    output = _run(['--git-dir', repository.path, 'show', '--format=%H%x00%h%x00%an%x00%ae%x00%aI%x00%s%x00%b', '--stat', '--patch', '--no-ext-diff', '--no-renames', commit]).stdout
    meta, _, diff = output.partition('\n')
    parts = meta.split('\x00', 6)
    return {'hash': commit, 'short_hash': parts[1] if len(parts) > 1 else commit[:7],
            'author': parts[2] if len(parts) > 2 else '', 'email': parts[3] if len(parts) > 3 else '',
            'date': parts[4] if len(parts) > 4 else '', 'message': parts[5] if len(parts) > 5 else '',
            'diff': diff}


def _resolve_commit(repository, revision):
    _ensure_remote_cache(repository)
    if not isinstance(revision, str) or not revision or len(revision) > 100:
        raise ValidationError('Choose a valid commit.')
    result = _run(['--git-dir', repository.path, 'rev-parse', '--verify', f'{revision}^{{commit}}'], check=False)
    if result.returncode:
        raise ValidationError('That commit does not exist in this repository.')
    return result.stdout.strip()


def diff_stat(repository, source, target):
    """Summarise a branch comparison without exposing its content."""
    source = validate_branch_name(repository, source)
    target = validate_branch_name(repository, target)
    diff = compare_revisions(repository, source, target)
    files, insertions, deletions = [], 0, 0
    for line in diff.splitlines():
        if line.startswith('diff --git '):
            path = line.split(' b/', 1)[-1].strip()
            if path not in files:
                files.append(path)
        elif line.startswith('+') and not line.startswith('+++'):
            insertions += 1
        elif line.startswith('-') and not line.startswith('---'):
            deletions += 1
    return {'files': files, 'insertions': insertions, 'deletions': deletions}


def compare_revisions(repository, source, target):
    source = validate_branch_name(repository, source)
    target = validate_branch_name(repository, target)
    if not branch_exists(repository, source) or not branch_exists(repository, target):
        raise ValidationError('Choose two existing branches.')
    return _run(['--git-dir', repository.path, 'diff', '--no-ext-diff', '--no-renames', f'{target}...{source}']).stdout


def compare_commits(repository, older, newer):
    older = _resolve_commit(repository, older)
    newer = _resolve_commit(repository, newer)
    return _run(['--git-dir', repository.path, 'diff', '--no-ext-diff', '--no-renames', older, newer]).stdout


def _merge_conflicts(repository, target_tip, source_tip):
    directory = Path(tempfile.mkdtemp(prefix='hackflow-merge-check-'))
    try:
        _run(['--git-dir', repository.path, 'worktree', 'add', '--detach', directory, target_tip], env=git_env())
        result = _run(['merge', '--no-commit', '--no-ff', source_tip], cwd=directory, check=False, env=git_env())
        if result.returncode == 0:
            return {}
        if result.returncode not in (1,):
            raise GitError(result.stderr.strip() or 'The merge preview failed.')
        paths = _run(['diff', '--name-only', '--diff-filter=U', '-z'], cwd=directory, text=False, env=git_env()).stdout.split(b'\0')
        conflicts = {}
        for raw_path in paths:
            if not raw_path:
                continue
            path = raw_path.decode('utf-8', errors='replace')
            from .security import normalize_repo_path
            safe_path, ignored = normalize_repo_path(path)
            if safe_path != path or ignored:
                raise GitError('A conflicted path is not safe to resolve.')
            source_result = _run(['--git-dir', repository.path, 'show', f'{source_tip}:{path}'], check=False, text=False)
            target_result = _run(['--git-dir', repository.path, 'show', f'{target_tip}:{path}'], check=False, text=False)
            result_file = directory / path
            try:
                proposed = result_file.read_bytes() if result_file.exists() else b''
                source_data = source_result.stdout if source_result.returncode == 0 else b''
                target_data = target_result.stdout if target_result.returncode == 0 else b''
                binary = any(b'\x00' in data for data in (source_data, target_data, proposed))
                if max(len(source_data), len(target_data), len(proposed)) > 500_000:
                    binary = True
                conflicts[path] = {
                    'source': '' if binary else source_data.decode('utf-8', errors='replace'),
                    'target': '' if binary else target_data.decode('utf-8', errors='replace'),
                    'result': '' if binary else proposed.decode('utf-8', errors='replace'),
                    'binary': binary,
                    'source_exists': source_result.returncode == 0,
                    'target_exists': target_result.returncode == 0,
                }
            except OSError as exc:
                raise GitError('A conflicted file could not be read.') from exc
        return conflicts
    finally:
        _run(['--git-dir', repository.path, 'worktree', 'remove', '--force', directory], check=False, env=git_env())
        shutil.rmtree(directory, ignore_errors=True)
        _run(['--git-dir', repository.path, 'worktree', 'prune'], check=False, env=git_env())


def merge_preview(repository, source, target):
    source = validate_branch_name(repository, source)
    target = validate_branch_name(repository, target)
    if source == target or not branch_exists(repository, source) or not branch_exists(repository, target):
        raise ValidationError('Choose two different existing branches.')
    with repository_lock(repository):
        source_tip, target_tip = resolve_branch(repository, source), resolve_branch(repository, target)
        conflicts = _merge_conflicts(repository, target_tip, source_tip)
    return {'source_tip': source_tip, 'target_tip': target_tip, 'conflicts': conflicts}


def merge_branches(repository, source, target, message, author, *, expected_source=None, expected_target=None,
                   allow_protected=False):
    source = validate_branch_name(repository, source)
    target = validate_branch_name(repository, target)
    if repository.is_protected(target) and not allow_protected:
        raise ValidationError('This branch is protected. Merge into it through an approved merge request.')
    message = ' '.join((message or '').replace('\x00', '').split()).strip()
    if not message or len(message) > 200:
        raise ValidationError('Enter a merge message between 1 and 200 characters.')
    with repository_lock(repository):
        source_tip, target_tip = resolve_branch(repository, source), resolve_branch(repository, target)
        if expected_source and source_tip != expected_source or expected_target and target_tip != expected_target:
            raise ValidationError('A branch changed during review. Refresh the merge request and try again.')
        if _merge_conflicts(repository, target_tip, source_tip):
            raise ValidationError('This merge has conflicts that must be resolved first.')
        with worktree(repository, target) as (directory, old_target):
            _run(['merge', '--no-ff', source, '-m', message], cwd=directory, env=git_env(author))
            new_commit = _run(['rev-parse', 'HEAD'], cwd=directory).stdout.strip()
            _run(['--git-dir', repository.path, 'update-ref', f'refs/heads/{target}', new_commit, old_target])
            _push_branch(repository, target)
    return new_commit


def finish_conflicted_merge(repository, source, target, target_tip, source_tip, resolutions, message, author,
                            *, allow_protected=False):
    if repository.is_protected(target) and not allow_protected:
        raise ValidationError('This branch is protected. Merge into it through an approved merge request.')
    message = ' '.join((message or '').replace('\x00', '').split()).strip()
    if not message or len(message) > 200:
        raise ValidationError('Enter a merge message between 1 and 200 characters.')
    with repository_lock(repository):
        if resolve_branch(repository, target) != target_tip or resolve_branch(repository, source) != source_tip:
            raise ValidationError('A branch changed during conflict resolution. Reopen the merge request.')
        conflicts = _merge_conflicts(repository, target_tip, source_tip)
        if set(resolutions) != set(conflicts):
            raise ValidationError('Resolve every conflicted file before completing the merge.')
        for path, content in resolutions.items():
            from .security import normalize_repo_path
            safe, ignored = normalize_repo_path(path)
            valid_binary_choice = isinstance(content, dict) and content.get('side') in ('source', 'target') and conflicts[path]['binary']
            valid_text = content is None or isinstance(content, str) and not any(marker in content for marker in ('<<<<<<<', '=======', '>>>>>>>'))
            if safe != path or ignored or not (valid_binary_choice or valid_text):
                raise ValidationError('Remove conflict markers and provide a valid result for every text file.')
        with worktree(repository, target) as (directory, old_target):
            _run(['merge', '--no-commit', '--no-ff', source], cwd=directory, check=False, env=git_env())
            for path, content in resolutions.items():
                dest = directory / Path(*path.split('/'))
                if isinstance(content, dict):
                    side_tip = source_tip if content['side'] == 'source' else target_tip
                    checkout = _run(['checkout', side_tip, '--', path], cwd=directory, check=False, env=git_env())
                    if checkout.returncode:
                        _run(['rm', '-f', '--', path], cwd=directory, check=False, env=git_env())
                    else:
                        _run(['add', '--force', '--', path], cwd=directory, env=git_env())
                    continue
                if content is None:
                    _run(['rm', '-f', '--', path], cwd=directory, check=False, env=git_env())
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding='utf-8', newline='')
                _run(['add', '--force', '--', path], cwd=directory, env=git_env())
            unmerged = _run(['diff', '--name-only', '--diff-filter=U'], cwd=directory, env=git_env()).stdout.strip()
            if unmerged:
                raise ValidationError('Resolve every conflicted file before completing the merge.')
            _run(['commit', '-m', message], cwd=directory, env=git_env(author))
            new_commit = _run(['rev-parse', 'HEAD'], cwd=directory).stdout.strip()
            _run(['--git-dir', repository.path, 'update-ref', f'refs/heads/{target}', new_commit, old_target])
            _push_branch(repository, target)
    return new_commit


def restore_commit(repository, branch, revision, message, author):
    branch = validate_branch_name(repository, branch)
    if not branch_exists(repository, branch):
        raise ValidationError('Choose an existing branch.')
    if repository.is_protected(branch):
        raise ValidationError('This branch is protected. Restore the version on another branch and use a merge request.')
    commit = _resolve_commit(repository, revision)
    message = ' '.join((message or f'Restore version {commit[:7]}').replace('\x00', '').split()).strip()
    if not message or len(message) > 200:
        raise ValidationError('Enter a restore message up to 200 characters.')
    with repository_lock(repository):
        parent = resolve_branch(repository, branch)
        tree = _run(['--git-dir', repository.path, 'rev-parse', f'{commit}^{{tree}}']).stdout.strip()
        created = _run(['--git-dir', repository.path, 'commit-tree', tree, '-p', parent, '-m', message], env=git_env(author)).stdout.strip()
        _run(['--git-dir', repository.path, 'update-ref', f'refs/heads/{branch}', created, parent])
        _push_branch(repository, branch)
    return created
