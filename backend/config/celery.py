"""Celery application configuration.

Background tasks live in the apps that own them (e.g. apps/bookings/tasks.py,
apps/notifications/tasks.py). Celery is used for work that must NOT block an
API request: email delivery and pending-booking expiration.
"""
import os

from celery import Celery
from celery.schedules import crontab

# Render workers must never silently boot development settings (which enable
# eager tasks and permissive CORS). Local CLI use keeps the dev default.
_default_settings = "config.settings.production" if os.environ.get("RENDER") else "config.settings.development"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", _default_settings)

app = Celery("jone_hotel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Release inventory held by abandoned pending bookings.
    "expire-pending-bookings": {
        "task": "apps.bookings.tasks.expire_pending_bookings",
        "schedule": crontab(minute="*/5"),
    },
    # Automatic checkout at the hotel's configured checkout time (idempotent,
    # row-locked; never checks out early). Runs every 5 minutes.
    "auto-checkout-due-bookings": {
        "task": "apps.bookings.tasks.auto_checkout_due_bookings",
        "schedule": crontab(minute="*/5"),
    },
    # 30-minute checkout warning to staff (deduplicated per stay).
    "checkout-due-soon-warnings": {
        "task": "apps.bookings.tasks.checkout_due_soon_warnings",
        "schedule": crontab(minute="*/5"),
    },
}
