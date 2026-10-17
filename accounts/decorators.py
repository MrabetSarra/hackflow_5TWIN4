from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*allowed_roles):
    """Require an authenticated user whose account has one of the given roles."""
    def decorator(view_func):
        @wraps(view_func)
        def check_role(request, *args, **kwargs):
            if getattr(request.user, 'role', None) not in allowed_roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return login_required(check_role)

    return decorator
