from urllib.parse import quote

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
