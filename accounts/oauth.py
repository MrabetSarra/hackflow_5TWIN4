import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Raised when an OAuth authentication error occurs."""
    pass


class OAuthProvider:
    name = ''
    auth_url = ''
    token_url = ''
    userinfo_url = ''
    scope = ''

    def get_client_id(self):
        raise NotImplementedError

    def get_client_secret(self):
        raise NotImplementedError

    def is_configured(self):
        return bool(self.get_client_id() and self.get_client_secret())

    def get_authorization_url(self, redirect_uri, state):
        params = {
            'client_id': self.get_client_id(),
            'redirect_uri': redirect_uri,
            'scope': self.scope,
            'state': state,
        }
        return f"{self.auth_url}?{urlencode(params)}"

    def get_user_info(self, code, redirect_uri):
        raise NotImplementedError


class GitHubOAuthProvider(OAuthProvider):
    name = 'github'
    auth_url = 'https://github.com/login/oauth/authorize'
    token_url = 'https://github.com/login/oauth/access_token'
    userinfo_url = 'https://api.github.com/user'
    emails_url = 'https://api.github.com/user/emails'
    scope = 'read:user user:email'

    def get_client_id(self):
        return getattr(settings, 'GITHUB_CLIENT_ID', '')

    def get_client_secret(self):
        return getattr(settings, 'GITHUB_CLIENT_SECRET', '')

    def get_user_info(self, code, redirect_uri):
        token_response = requests.post(
            self.token_url,
            headers={'Accept': 'application/json'},
            data={
                'client_id': self.get_client_id(),
                'client_secret': self.get_client_secret(),
                'code': code,
                'redirect_uri': redirect_uri,
            },
            timeout=15,
        )
        if not token_response.ok:
            raise OAuthError(f"GitHub token exchange failed: {token_response.text}")

        token_data = token_response.json()
        access_token = token_data.get('access_token')
        if not access_token:
            error_desc = token_data.get('error_description') or token_data.get('error', 'No access token')
            raise OAuthError(f"GitHub authentication error: {error_desc}")

        auth_headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'HackFlow-App',
        }

        user_response = requests.get(self.userinfo_url, headers=auth_headers, timeout=15)
        if not user_response.ok:
            raise OAuthError("Failed to fetch user profile from GitHub.")

        raw_user = user_response.json()
        email = raw_user.get('email')

        # If email is private in GitHub profile, fetch from emails endpoint
        if not email:
            emails_res = requests.get(self.emails_url, headers=auth_headers, timeout=15)
            if emails_res.ok:
                emails_list = emails_res.json()
                for item in emails_list:
                    if item.get('primary') and item.get('verified'):
                        email = item.get('email')
                        break
                if not email and emails_list:
                    email = emails_list[0].get('email')

        if not email:
            raise OAuthError("Could not retrieve a verified email address from your GitHub account.")

        full_name = (raw_user.get('name') or '').strip()
        first_name = ''
        last_name = ''
        if full_name:
            parts = full_name.split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''

        return {
            'email': email.lower(),
            'username': raw_user.get('login') or email.split('@')[0],
            'first_name': first_name,
            'last_name': last_name,
            'github_url': raw_user.get('html_url') or '',
            'bio': raw_user.get('bio') or '',
        }


class GoogleOAuthProvider(OAuthProvider):
    name = 'google'
    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth'
    token_url = 'https://oauth2.googleapis.com/token'
    userinfo_url = 'https://openidconnect.googleapis.com/v1/userinfo'
    scope = 'openid email profile'

    def get_client_id(self):
        return getattr(settings, 'GOOGLE_CLIENT_ID', '')

    def get_client_secret(self):
        return getattr(settings, 'GOOGLE_CLIENT_SECRET', '')

    def get_authorization_url(self, redirect_uri, state):
        params = {
            'client_id': self.get_client_id(),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': self.scope,
            'state': state,
            'access_type': 'online',
            'prompt': 'select_account',
        }
        return f"{self.auth_url}?{urlencode(params)}"

    def get_user_info(self, code, redirect_uri):
        token_response = requests.post(
            self.token_url,
            data={
                'client_id': self.get_client_id(),
                'client_secret': self.get_client_secret(),
                'code': code,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=15,
        )
        if not token_response.ok:
            raise OAuthError(f"Google token exchange failed: {token_response.text}")

        token_data = token_response.json()
        access_token = token_data.get('access_token')
        if not access_token:
            raise OAuthError("Google authentication error: No access token received.")

        user_response = requests.get(
            self.userinfo_url,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=15,
        )
        if not user_response.ok:
            raise OAuthError("Failed to fetch user profile from Google.")

        raw_user = user_response.json()
        email = raw_user.get('email')
        if not email:
            raise OAuthError("Could not retrieve an email address from your Google account.")

        return {
            'email': email.lower(),
            'username': email.split('@')[0],
            'first_name': raw_user.get('given_name') or '',
            'last_name': raw_user.get('family_name') or '',
            'github_url': '',
            'bio': '',
        }


PROVIDERS = {
    'github': GitHubOAuthProvider(),
    'google': GoogleOAuthProvider(),
}


def get_oauth_provider(name):
    provider = PROVIDERS.get(name.lower())
    if not provider:
        raise ValueError(f"Unknown OAuth provider: {name}")
    return provider


ALLOWED_REGISTRATION_ROLES = ('student', 'mentor')


def get_or_create_oauth_user(user_info, provider_name, role='student'):
    """
    Finds an existing user by email or creates a new student/mentor user.
    Creating admin or organization accounts via OAuth is explicitly forbidden.
    """
    User = get_user_model()
    email = user_info['email'].strip().lower()

    user = User.objects.filter(email__iexact=email).first()
    if user:
        # If GitHub login and github_url is not set yet on existing user
        if provider_name == 'github' and user_info.get('github_url') and not user.github_url:
            user.github_url = user_info['github_url']
            user.save(update_fields=['github_url'])
        return user, False

    # Strictly enforce that only student or mentor can ever be created via OAuth
    if role not in ALLOWED_REGISTRATION_ROLES:
        raise ValueError("Création interdite : seuls les rôles 'student' et 'mentor' sont autorisés.")

    # Create new user
    base_username = user_info.get('username') or email.split('@')[0]
    clean_username = ''.join(c for c in base_username if c.isalnum() or c in ('_', '-')) or 'user'
    username = clean_username
    counter = 1
    while User.objects.filter(username__iexact=username).exists():
        username = f"{clean_username}{counter}"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=email,
        first_name=user_info.get('first_name') or '',
        last_name=user_info.get('last_name') or '',
        role=role,
        github_url=user_info.get('github_url') or '',
        bio=user_info.get('bio') or '',
    )
    user.set_unusable_password()
    user.save()
    return user, True
