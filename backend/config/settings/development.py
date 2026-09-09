"""Development settings: SQLite, console email, eager Celery, permissive CORS."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# The separately hosted frontend may run on any local port during development.
# This is intentionally dev-only; production uses an explicit origin allowlist.
CORS_ALLOW_ALL_ORIGINS = True

# Emails print to the terminal instead of leaving the machine.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Background tasks run synchronously so no Redis/worker is needed locally.
CELERY_TASK_ALWAYS_EAGER = True

# In-process cache is fine on a single dev machine.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jone-cache",
    }
}
