"""Celery application configuration.

Background tasks live in the apps that own them (e.g. apps/bookings/tasks.py,
apps/notifications/tasks.py). Celery is used for work that must NOT block an
API request: email delivery and pending-booking expiration.
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("jone_hotel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Release inventory held by abandoned pending bookings.
    "expire-pending-bookings": {
        "task": "apps.bookings.tasks.expire_pending_bookings",
        "schedule": crontab(minute="*/5"),
    },
}
