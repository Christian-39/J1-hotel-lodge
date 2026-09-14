"""Celery tasks owned by the notifications app."""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("apps")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="apps.notifications.send_email",
    autoretry_for=(),
)
def send_email_task(self, subject, message, recipients):
    """Deliver email off the request path; retry transient SMTP failures."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[r for r in (recipients or []) if r],
            fail_silently=False,
        )
    except Exception as exc:
        # Never include SMTP credentials/API keys in logs.
        logger.warning("Email task failed with %s; retrying if attempts remain", exc.__class__.__name__)
        raise self.retry(exc=exc)
