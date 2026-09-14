"""Transactional email delivery that never breaks API state changes.

Application operational emails (booking confirmations, cancellation requests,
refund lifecycle notices, staff alerts) are sent through Django's configured
email backend — normally Brevo SMTP or another transactional SMTP provider in
production, console email in development.

Paystack payment receipts are a separate provider feature controlled in the
Paystack Dashboard. This module does not attempt to send or mimic Paystack
transaction receipts.
"""
import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("apps")


def _clean_recipients(recipients):
    cleaned = []
    for recipient in recipients or []:
        value = str(recipient or "").strip()
        if not value or "\n" in value or "\r" in value:
            continue
        _, addr = parseaddr(value)
        if addr and "@" in addr:
            cleaned.append(addr)
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(cleaned))


def _send(subject, message, recipients):
    recipients = _clean_recipients(recipients)
    if not recipients:
        return
    subject = str(subject or "").replace("\r", " ").replace("\n", " ")[:255]
    try:
        send_mail(
            subject=subject,
            message=message or "",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception as exc:
        # Do not log SMTP usernames/passwords/API keys. Exception class is
        # enough for operations; provider logs carry delivery details.
        logger.warning("Failed to send email '%s' to %s (%s)", subject, recipients, exc.__class__.__name__)


def send_email_safe(subject, message, recipients):
    """Queue (or directly send) an email; swallow all delivery errors."""
    recipients = _clean_recipients(recipients)
    if not recipients:
        return
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        _send(subject, message, recipients)
        return
    try:
        from apps.notifications.tasks import send_email_task

        send_email_task.delay(subject, message, recipients)
    except Exception as exc:
        logger.warning("Could not queue email task; sending synchronously (%s)", exc.__class__.__name__)
        _send(subject, message, recipients)
