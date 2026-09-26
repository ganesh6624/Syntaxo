"""
Django settings for Syntaxo.

Every value can be overridden with an environment variable (see README.md).
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_DIR = BASE_DIR / "public"


def _load_secret() -> str:
    """JWT / Django secret: JWT_SECRET env var, else generated once and kept in data/.secret."""
    if os.environ.get("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    f = DATA_DIR / ".secret"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    s = secrets.token_hex(48)
    f.write_text(s, encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return s


SECRET_KEY = _load_secret()
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "https://*.e2b.app").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.http.ApiMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(DATA_DIR / "syntaxo.sqlite3")),
        "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "syntaxo"}}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# Django admin static files (the game UI itself is served from public/ by core.views)
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Request bodies for the JSON API are small; refuse anything bigger than 50 KB.
API_MAX_BODY = 50 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# ── App settings ─────────────────────────────────────────
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "30"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin123")
APP_TZ = os.environ.get("APP_TZ", "Asia/Kolkata")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "syntaxo": {"handlers": ["console"], "level": "INFO"},
        "django.request": {"handlers": ["console"], "level": "ERROR"},
    },
}

# ── HTTPS hardening — set HTTPS_ONLY=1 when the site is served over https (behind nginx / a load balancer) ──
HTTPS_ONLY = os.environ.get("HTTPS_ONLY") == "1"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = HTTPS_ONLY
SECURE_HSTS_SECONDS = 31_536_000 if HTTPS_ONLY else 0
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = HTTPS_ONLY   # (only the /django-admin/ login uses these cookies)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# The app may be shown inside an iframe (live previews / embedding), so X-Frame-Options is not sent.
SILENCED_SYSTEM_CHECKS = ["security.W002"]
