"""Django settings for Shop POS.

The app runs locally on the shop laptop with SQLite. Everything that changes
at runtime (database, uploaded logo, generated secret key) lives in DATA_DIR,
so the code folder can be replaced on upgrade without touching shop data.

It can also run online (on Vercel): set DATABASE_URL to a Postgres database.
Online there is no lasting disk, so the logo is kept in the database, the
shop's receipt printer and folder backups are off, and settings come from
environment variables.
"""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.environ.get("VERCEL"))
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
# Online = no shop laptop: no printer, no folder backups, uploads kept in the database.
ONLINE = ON_VERCEL or os.environ.get("SHOPPOS_ONLINE") == "1"
DATA_DIR = Path(os.environ.get("SHOPPOS_DATA_DIR", "/tmp/shoppos" if ON_VERCEL else BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key():
    if os.environ.get("SHOPPOS_SECRET_KEY"):
        return os.environ["SHOPPOS_SECRET_KEY"]
    if ONLINE:
        # A key made on the fly would differ between servers and log everyone out.
        raise ImproperlyConfigured("Set SHOPPOS_SECRET_KEY to a long random string.")
    key_file = DATA_DIR / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50))
    return key_file.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("SHOPPOS_DEBUG", "0" if ONLINE else "1") == "1"
ALLOWED_HOSTS = os.environ.get("SHOPPOS_ALLOWED_HOSTS", ".vercel.app" if ON_VERCEL else "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get(
    "SHOPPOS_CSRF_ORIGINS", "https://*.vercel.app" if ON_VERCEL else "").split(",") if o]
if ONLINE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.catalog",
    "apps.partners",
    "apps.inventory",
    "apps.sales",
    "apps.documents",
    "apps.finance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.LoginRequiredMiddleware",
    "apps.core.middleware.DailyBackupMiddleware",
]

ROOT_URLCONF = "shoppos.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.shop",
            ],
        },
    },
]

WSGI_APPLICATION = "shoppos.wsgi.application"

if DATABASE_URL:
    import dj_database_url

    # Serverless functions come and go, so connections are not kept open between requests.
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0, conn_health_checks=True)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "shoppos.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = DATA_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)
MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

# Take the evening backup automatically while the POS is in use.
AUTO_BACKUP = os.environ.get("SHOPPOS_AUTO_BACKUP", "0" if ONLINE else "1") == "1"

STORAGES = {
    "default": {"BACKEND": "apps.core.storage.DatabaseStorage" if ONLINE
                else "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
if ONLINE:
    # No collectstatic step online: WhiteNoise serves the files straight from the code folders.
    WHITENOISE_USE_FINDERS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {"class": "logging.FileHandler", "filename": DATA_DIR / "shoppos.log", "level": "WARNING"},
        "console": {"class": "logging.StreamHandler", "level": "INFO"},
    },
    "root": {"handlers": ["console"] if ONLINE else ["file", "console"], "level": "INFO"},
}
