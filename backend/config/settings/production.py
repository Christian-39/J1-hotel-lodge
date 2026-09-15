"""Production settings: MySQL, strict security, B2 media, Redis cache.

Fails fast on missing critical configuration instead of silently falling back
to insecure defaults.
"""
import dj_database_url
from decouple import Csv, config

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = config("DJANGO_SECRET_KEY")  # required — no insecure default
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", cast=Csv())

# --- Database: MySQL 8+ via DATABASE_URL or components ----------------------
_database_url = config("DATABASE_URL", default="")
if _database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default="3306"),
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
# Guard: refuse to boot production on SQLite.
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    raise RuntimeError("Production requires MySQL (set DATABASE_URL or DB_* variables).")

# --- CORS / CSRF: explicit allowlists only ----------------------------------
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())
CORS_ALLOW_ALL_ORIGINS = False

# --- HTTPS / browser security headers ---------------------------------------
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# --- Static files via WhiteNoise --------------------------------------------
# Preserve the base-selected media backend (B2 when configured, local
# otherwise); only production static files are replaced by WhiteNoise.
STORAGES["staticfiles"] = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
}

# A deployed Paystack callback must be public HTTPS, never a development host.
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlparse
_callback = urlparse(PAYMENT_CALLBACK_URL)
if _callback.scheme != "https" or _callback.hostname in {"localhost", "127.0.0.1", None}:
    raise ImproperlyConfigured(
        "PAYMENT_CALLBACK_URL (or FRONTEND_URL fallback) must be a public HTTPS URL in production."
    )


# --- Redis-backed cache (throttles, settings cache, hot public content) ------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,  # noqa: F405
    }
}

# --- Email over SMTP ----------------------------------------------------------
# Production MUST use a real SMTP backend. If EMAIL_BACKEND is left at the
# console default (or forced to console) the "email" would only be printed to a
# log the guest never sees — the exact silent-failure this deploy must prevent.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
if "console" in EMAIL_BACKEND or "dummy" in EMAIL_BACKEND:
    raise ImproperlyConfigured(
        "Production must not use the console/dummy email backend — guests would "
        "never receive receipts. Set EMAIL_BACKEND to the SMTP backend."
    )
if EMAIL_BACKEND.endswith("smtp.EmailBackend"):
    # Fail fast on missing SMTP credentials instead of letting the Celery
    # worker discover them at send time and silently fail delivery.
    _missing = [
        name for name in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
        if not (globals().get(name) or "").strip()
    ]
    if _missing:
        raise ImproperlyConfigured(
            "Production SMTP is not fully configured. Missing: "
            + ", ".join(_missing)
            + ". For a Gmail/Google account you MUST use a 16-character App "
            "Password (not the normal account password), with EMAIL_HOST="
            "smtp.gmail.com, EMAIL_PORT=587, EMAIL_USE_TLS=True."
        )

# Celery workers run tasks out-of-process in production. Guard against a broker
# that was never configured — otherwise queued receipts would sit unconsumed.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
if not CELERY_TASK_ALWAYS_EAGER and not (REDIS_URL or "").strip():  # noqa: F405
    raise ImproperlyConfigured(
        "REDIS_URL (Celery broker) is required in production so the worker can "
        "consume queued email tasks."
    )
