from django.contrib.auth import get_user_model

from .models import AuditLog, UserProfile
from .roles import is_owner


def log(action, *, user=None, obj=None, reason="", authorised_by=None, **details):
    return AuditLog.objects.create(
        action=action,
        user=user if user and user.is_authenticated else None,
        authorised_by=authorised_by,
        object_repr=str(obj)[:200] if obj is not None else "",
        reason=reason[:300],
        details={k: str(v) for k, v in details.items()},
    )


def verify_owner_pin(pin):
    """Return the owner whose PIN matches, or None."""
    if not pin:
        return None
    for profile in UserProfile.objects.select_related("user").exclude(pin_hash=""):
        if profile.user.is_active and is_owner(profile.user) and profile.check_pin(pin):
            return profile.user
    return None


def owners():
    User = get_user_model()
    return [u for u in User.objects.filter(is_active=True) if is_owner(u)]
