"""Transactional email delivery with real, tracked lifecycle.

The rule this module enforces: an API request may report that an email was
**queued**, but it must NEVER report "sent" for work that has only been placed
on a queue. Actual delivery is performed by the Celery worker, which updates a
persistent ``EmailLog`` row (PENDING → QUEUED → SENDING → SENT / FAILED /
RETRYING). Staff/admins can then see whether the message truly left the system.

Application operational emails (booking confirmations, cancellation requests,
refund lifecycle notices, staff alerts, password resets, payment receipts) all
go through here so the fix is central, not receipt-only.

Security: SMTP credentials, API keys, tokens and passwords are NEVER logged or
stored on the EmailLog. Only the exception class and a scrubbed, human-readable
reason are persisted.
"""
import logging
from email.utils import parseaddr

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps")


def clean_recipients(recipients):
    """Validate + de-duplicate recipient addresses (header-injection safe)."""
    cleaned = []
    for recipient in recipients or []:
        value = str(recipient or "").strip()
        if not value or "\n" in value or "\r" in value:
            continue
        _, addr = parseaddr(value)
        if addr and "@" in addr and "." in addr.split("@")[-1]:
            cleaned.append(addr)
    return list(dict.fromkeys(cleaned))


# Back-compat alias (older imports).
_clean_recipients = clean_recipients


def send_email_safe(
    subject,
    message,
    recipients,
    *,
    html_message="",
    kind="GENERIC",
    booking_reference="",
    payment_reference="",
    booking_id=None,
    attach_receipt_pdf=False,
    created_by=None,
):
    """Record + queue (or eagerly send) a transactional email.

    ``message`` is the required plain-text body (also the fallback for clients
    that cannot render HTML). ``html_message`` is an optional styled HTML
    alternative — when supplied the worker delivers a proper
    ``multipart/alternative`` message, never HTML-as-escaped-text.

    Returns the :class:`EmailLog` instance (or ``None`` when there is no valid
    recipient). Errors never propagate to the API caller — but unlike the old
    implementation they are no longer *hidden*: every attempt is tracked on the
    returned EmailLog row and surfaced to staff.
    """
    from apps.notifications.models import EmailLog

    recipients = clean_recipients(recipients)
    if not recipients:
        logger.warning("Email '%s' skipped: no valid recipient", str(subject)[:80])
        return None

    subject = str(subject or "").replace("\r", " ").replace("\n", " ")[:255]

    # One EmailLog row per recipient so status is meaningful per mailbox.
    log = None
    for addr in recipients:
        try:
            row = EmailLog.objects.create(
                to_email=addr,
                subject=subject,
                body=message or "",
                html_body=html_message or "",
                kind=kind if kind in EmailLog.Kind.values else EmailLog.Kind.GENERIC,
                booking_reference=booking_reference or "",
                payment_reference=payment_reference or "",
                booking_id=booking_id,
                attach_receipt_pdf=bool(attach_receipt_pdf),
                created_by=created_by if getattr(created_by, "pk", None) else None,
                status=EmailLog.Status.PENDING,
            )
            _dispatch(row)
            log = log or row
        except Exception as exc:  # email bookkeeping must not break core state
            logger.error(
                "EMAIL_FAILED email_log_id=- stage=LOG category=%s kind=%s booking=%s",
                exc.__class__.__name__, kind, booking_reference or "-",
            )
    return log


def _dispatch(log):
    """Hand one EmailLog to Celery without ever falling back to SMTP inline.

    Eager execution is retained only for local development/test settings. The
    production settings reject eager mode at startup. A broker outage is
    recorded as FAILED at the queue stage; it must never turn an HTTP worker
    into an SMTP worker or delay booking/payment state changes.
    """
    from apps.notifications.models import EmailLog
    from apps.notifications.tasks import send_email_task

    logger.info("EMAIL_QUEUE_START email_log_id=%s kind=%s booking=%s", log.pk, log.kind, log.booking_reference or "-")
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        try:
            send_email_task.delay(log.id)
        except Exception as exc:  # task records its own delivery status
            logger.info("Eager EmailLog#%s ended with %s", log.pk, exc.__class__.__name__)
        return

    try:
        # retry=False prevents Kombu's producer retry loop from pinning a web
        # worker when Redis is unavailable. Broker socket timeouts are bounded
        # separately in settings.
        result = send_email_task.apply_async(args=[log.id], retry=False)
    except Exception as exc:  # broker unavailable; SMTP is deliberately NOT called
        EmailLog.objects.filter(pk=log.pk).update(
            status=EmailLog.Status.FAILED,
            failure_stage=EmailLog.FailureStage.QUEUE,
            error_class=exc.__class__.__name__,
            error_message="Email delivery could not be queued. Please retry later.",
            failed_at=timezone.now(),
        )
        logger.warning("EMAIL_FAILED email_log_id=%s stage=QUEUE category=%s", log.pk, exc.__class__.__name__)
        return

    EmailLog.objects.filter(pk=log.pk, status=EmailLog.Status.PENDING).update(
        status=EmailLog.Status.QUEUED,
        queued_at=timezone.now(),
        task_id=getattr(result, "id", "") or "",
    )
    logger.info("EMAIL_QUEUED email_log_id=%s task_id=%s", log.pk, getattr(result, "id", "") or "-")
