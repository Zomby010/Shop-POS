from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Shop"

    def ready(self):
        from django.contrib.auth import get_user_model

        from . import signals

        post_migrate.connect(signals.create_groups, sender=self)
        post_save.connect(signals.create_profile, sender=get_user_model())
