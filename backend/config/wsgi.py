"""WSGI config for production (gunicorn config.wsgi)."""
import os

from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

load_dotenv()
# A stale Render environment previously selected development settings, enabling
# eager Celery and permissive CORS in production. Force the production module
# on Render rather than crashing the deploy; local WSGI also defaults safely.
if os.environ.get("RENDER"):
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
