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
    kind="GENERIC",
    booking_reference="",
    payment_reference="",
    booking_id=None,
    attach_receipt_pdf=False,
    created_by=None,
):
    """Record + queue (or eagerly send) a transactional email.

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
        row = EmailLog.objects.create(
            to_email=addr,
            subject=subject,
            body=message or "",
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
    return log


def _dispatch(log):
    """Hand a single EmailLog row to the worker, or run it eagerly."""
    from apps.notifications.models import EmailLog
    from apps.notifications.tasks import send_email_task

    eager = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)

    if eager:
        # .delay() executes the task inline. The task records its own final
        # status (SENT / FAILED / RETRYING) and, when retries are exhausted,
        # may raise — that exception means the task RAN, not that the broker
        # was unreachable, so we must NOT fall back to a duplicate send.
        try:
            send_email_task.delay(log.id)
        except Exception as exc:  # noqa: BLE001 - status already persisted by task
            logger.info(
                "Eager email task for EmailLog#%s ended with %s (status already recorded)",
                log.pk, exc.__class__.__name__,
            )
        return

    # Real async path: enqueue on the broker. An exception here means the
    # broker is unreachable and the task never ran — mark it visibly and make a
    # best-effort synchronous send so a broker outage cannot silently swallow a
    # critical transactional email.
    try:
        result = send_email_task.delay(log.id)
    except Exception as exc:
        logger.warning(
            "Could not queue email task for EmailLog#%s (%s); sending synchronously",
            log.pk, exc.__class__.__name__,
        )
        from apps.notifications.tasks import deliver_email_log

        deliver_email_log(log.pk, allow_retry=False)
        return

    EmailLog.objects.filter(pk=log.pk, status=EmailLog.Status.PENDING).update(
        status=EmailLog.Status.QUEUED,
        queued_at=timezone.now(),
        task_id=getattr(result, "id", "") or "",
    )
