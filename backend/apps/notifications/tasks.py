"""Celery tasks owned by the notifications app."""
import logging

from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger("apps")


@shared_task(bind=True, max_retries=3, default_retry_delay=30, name="apps.notifications.send_email")
def send_email_task(self, subject, message, recipients):
    """Deliver email off the request path; retry transient SMTP failures."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception as exc:
        logger.warning("Email task failed (%s); retrying if attempts remain", exc)
        raise self.retry(exc=exc)
