"""Email delivery that never breaks an API request.

Emails are handed to a Celery task when a worker is available (production)
and sent synchronously/straight to the console backend in development.
Failures are logged — a booking may not fail because SMTP hiccuped.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("apps")


def _send(subject, message, recipients):
    if not recipients:
        return
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[r for r in recipients if r],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send email '%s' to %s", subject, recipients)


def send_email_safe(subject, message, recipients):
    """Queue (or directly send) an email; swallow all delivery errors."""
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        return
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        _send(subject, message, recipients)
        return
    try:
        from apps.notifications.tasks import send_email_task

        send_email_task.delay(subject, message, recipients)
    except Exception:
        logger.exception("Could not queue email task; sending synchronously")
        _send(subject, message, recipients)
