from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect

OPEN_PREFIXES = ("/login/", "/static/", "/media/", "/admin/login/")


class LoginRequiredMiddleware:
    """Every page needs a login except the login page and static files."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(OPEN_PREFIXES):
            return redirect(f"/login/?next={quote(request.get_full_path())}")
        return self.get_response(request)


class DailyBackupMiddleware:
    """Takes the evening backup automatically while the shop is using the POS."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.AUTO_BACKUP and request.user.is_authenticated:
            from .backup import maybe_run_daily_backup

            maybe_run_daily_backup()
        return response
