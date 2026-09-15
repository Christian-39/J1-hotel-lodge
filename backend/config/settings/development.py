"""Development settings: SQLite, console email, eager Celery, permissive CORS.

Defaults are developer-friendly (emails print to the terminal, tasks run
in-process so no Redis/worker is required). BUT every one of those defaults is
now overridable from the environment, so a developer who has filled in real
SMTP / Redis credentials in ``.env`` gets the real behaviour instead of having
their configuration silently discarded.
"""
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# The separately hosted frontend may run on any local port during development.
# This is intentionally dev-only; production uses an explicit origin allowlist.
CORS_ALLOW_ALL_ORIGINS = True

# Emails print to the terminal by default (nothing leaves the machine), but if
# you set EMAIL_BACKEND in .env — e.g. the SMTP backend with real credentials —
# that wins, so you can test real delivery locally. Previously this line
# hard-coded the console backend and threw the .env value away, which meant a
# fully-configured SMTP setup still only printed to the console and the guest
# never received anything.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

# Background tasks run synchronously by default so no Redis/worker is needed
# locally. Override to False in .env once you are running a real Celery worker.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=True, cast=bool)

# In-process cache is fine on a single dev machine.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jone-cache",
    }
}
