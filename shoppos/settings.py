"""Django settings for Shop POS.

The app runs locally on the shop laptop with SQLite. Everything that changes
at runtime (database, uploaded logo, generated secret key) lives in DATA_DIR,
so the code folder can be replaced on upgrade without touching shop data.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SHOPPOS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key():
    if os.environ.get("SHOPPOS_SECRET_KEY"):
        return os.environ["SHOPPOS_SECRET_KEY"]
    key_file = DATA_DIR / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50))
    return key_file.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("SHOPPOS_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("SHOPPOS_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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
AUTO_BACKUP = os.environ.get("SHOPPOS_AUTO_BACKUP", "1") == "1"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {"class": "logging.FileHandler", "filename": DATA_DIR / "shoppos.log", "level": "WARNING"},
        "console": {"class": "logging.StreamHandler", "level": "INFO"},
    },
    "root": {"handlers": ["file", "console"], "level": "INFO"},
}
