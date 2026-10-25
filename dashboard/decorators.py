from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def user_is_manager(user):
    """True for superusers, staff members and promoted manager profiles."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == profile.ROLE_MANAGER)


def manager_required(view_func):
    """Restrict a view to managers/admins (still requires login)."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not user_is_manager(request.user):
            messages.error(request, "You do not have permission to access the management dashboard.")
            return redirect("cars:home")
        return view_func(request, *args, **kwargs)

    return _wrapped
