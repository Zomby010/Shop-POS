"""Role helpers. Roles are Django groups; superusers count as owners."""

from functools import wraps

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

OWNER = "Owner"
CASHIER = "Cashier"
STOCK_CLERK = "Stock clerk"
ALL_ROLES = [OWNER, CASHIER, STOCK_CLERK]


def ensure_groups():
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


def user_roles(user):
    if not user.is_authenticated:
        return set()
    if not hasattr(user, "_role_cache"):
        user._role_cache = set(user.groups.values_list("name", flat=True))
    return user._role_cache


def is_owner(user):
    return user.is_authenticated and (user.is_superuser or OWNER in user_roles(user))


def has_role(user, *roles):
    """Owners pass every role check."""
    return is_owner(user) or bool(user_roles(user) & set(roles))


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


owner_required = role_required(OWNER)
