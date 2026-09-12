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
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


# --- Redis-backed cache (throttles, settings cache, hot public content) ------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,  # noqa: F405
    }
}

# --- Email over SMTP ----------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# Celery workers run tasks out-of-process in production.
CELERY_TASK_ALWAYS_EAGER = False
