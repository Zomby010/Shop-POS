def create_groups(sender, **kwargs):
    from .roles import ensure_groups

    ensure_groups()


def create_profile(sender, instance, created, **kwargs):
    from .models import UserProfile

    if created:
        UserProfile.objects.get_or_create(user=instance)
