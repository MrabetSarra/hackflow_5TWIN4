"""Minimal GitHub REST client used only on the server side."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings


class GitHubError(Exception):
    """A safe, user-displayable error from the GitHub integration."""


def _configuration():
    token = getattr(settings, 'GITHUB_TOKEN', '')
    owner = getattr(settings, 'GITHUB_OWNER', '')
    if not token or not owner:
        raise GitHubError(
            'GitHub is not configured. Set GITHUB_TOKEN and GITHUB_OWNER in '
            'the server environment before using repositories.'
        )
    return token, owner


def _request(method, endpoint, *, payload=None, expected=(200, 201)):
    token, _owner = _configuration()
    api_url = getattr(settings, 'GITHUB_API_URL', 'https://api.github.com')
    url = f'{api_url.rstrip("/")}{endpoint}'
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(url, data=body, method=method, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'HackFlow',
        **({'Content-Type': 'application/json'} if body is not None else {}),
    })
    try:
        with urlopen(request, timeout=getattr(settings, 'GITHUB_API_TIMEOUT', 15)) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        status = error.code
        if status == 404:
            raise GitHubError('The GitHub repository is unavailable or you no longer have access to it.') from None
        if status == 401:
            raise GitHubError('GitHub rejected the configured credential. Check GITHUB_TOKEN.') from None
        if status in (403, 429):
            if error.headers.get('X-RateLimit-Remaining') == '0' or error.headers.get('Retry-After'):
                raise GitHubError('GitHub API rate limit reached. Try again later.') from None
            raise GitHubError('GitHub denied this operation. Check token permissions and organization access.') from None
        if status == 422:
            raise GitHubError('GitHub rejected the repository details, or a repository with that name already exists.') from None
        raise GitHubError(f'GitHub returned HTTP {status}. Try again later.') from None
    except (URLError, TimeoutError, OSError):
        raise GitHubError('GitHub could not be reached. Check the connection and try again.') from None

    if status not in expected:
        raise GitHubError(f'GitHub returned HTTP {status}. Try again later.')
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GitHubError('GitHub returned an invalid response. Try again later.') from None


def _repo_path(owner, name):
    return f'/repos/{quote(owner, safe="")}/{quote(name, safe="")}'


def create_repository(repository, *, auto_init=True):
    """Create a real remote; never adopts or overwrites a name collision."""
    _token, owner = _configuration()
    private = getattr(settings, 'GITHUB_PRIVATE_REPOSITORIES', True)
    owner_info = _request('GET', f'/users/{quote(owner, safe="")}')
    endpoint = (
        '/user/repos' if owner_info.get('type', '').casefold() == 'user'
        else f'/orgs/{quote(owner, safe="")}/repos'
    )
    data = _request('POST', endpoint, payload={
        'name': f'hackflow-{repository.team_id}-{repository.slug}'[:100],
        'description': repository.description[:350],
        'private': bool(private),
        'auto_init': bool(auto_init),
    }, expected=(201,))
    return save_remote_metadata(repository, data)


def refresh_repository(repository):
    """Refresh IDs/URLs/default branch, following GitHub rename redirects."""
    if repository.remote_provider != 'github' or not repository.remote_owner or not repository.remote_name:
        raise GitHubError('This HackFlow repository is not linked to a GitHub repository.')
    data = _request('GET', _repo_path(repository.remote_owner, repository.remote_name))
    save_remote_metadata(repository, data)
    return data


def save_remote_metadata(repository, data):
    repository.remote_provider = 'github'
    repository.remote_id = data.get('id')
    repository.remote_node_id = data.get('node_id', '')[:100]
    repository.remote_owner = (data.get('owner') or {}).get('login', '')[:100]
    repository.remote_name = data.get('name', '')[:100]
    repository.remote_url = data.get('html_url', '')[:500]
    repository.clone_url = data.get('clone_url', '')[:500]
    repository.default_branch = data.get('default_branch') or repository.default_branch
    repository.save(update_fields=[
        'remote_provider', 'remote_id', 'remote_node_id', 'remote_owner',
        'remote_name', 'remote_url', 'clone_url', 'default_branch',
    ])
    return data
