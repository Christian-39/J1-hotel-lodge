"""Transactional email delivery with real, tracked lifecycle — SYNCHRONOUS.

The rules this module enforces:

1. Email is delivered DIRECTLY by the Django process handling the request.
   There is deliberately NO task queue (no Celery/Redis broker) between the
   application and the SMTP server: when a staff member clicks "Send receipt"
   — or when a Paystack payment is verified — Django itself opens the SMTP
   connection and waits for the result before the API response is final.
2. Every attempt is recorded on a persistent ``EmailLog`` row
   (PENDING → SENDING → SENT / FAILED) so staff see whether a message truly
   left the system. An API call may only report success AFTER the SMTP send
   has actually succeeded — "queued" is never reported as an outcome.
3. Email success and business state (booking/payment) stay separate: an SMTP
   failure marks the EmailLog FAILED and is logged, but it never rolls back a
   verified payment or a committed booking.

Application operational emails (booking confirmations, cancellation requests,
refund lifecycle notices, staff alerts, password resets, payment receipts) all
go through here so the behaviour is central, not receipt-only.

Security: SMTP credentials, API keys, tokens and passwords are NEVER logged or
stored on the EmailLog. Only the exception class and a scrubbed, human-readable
reason are persisted.
"""
import logging
from email.utils import parseaddr

from django.db import transaction
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
    """Record + deliver a transactional email NOW; returns its EmailLog row.

    ``message`` is the required plain-text body (also the fallback for clients
    that cannot render HTML). ``html_message`` is an optional styled HTML
    alternative — when supplied the delivery builds a proper
    ``multipart/alternative`` message, never HTML-as-escaped-text.

    Delivery is SYNCHRONOUS: this function performs the actual SMTP send in the
    calling process (during the current HTTP request / management command) and
    the returned EmailLog row reflects the REAL outcome (SENT or FAILED). There
    is no Celery task, broker or worker anywhere in this path.

    Errors never propagate to the caller — but they are never hidden either:
    the exception class and a credential-free reason are stored on the row and
    logged server-side, so callers can surface an honest failure result.
    """
    from apps.notifications.models import EmailLog
    from apps.notifications.tasks import deliver_email_log

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
            html_body=html_message or "",
            kind=kind if kind in EmailLog.Kind.values else EmailLog.Kind.GENERIC,
            booking_reference=booking_reference or "",
            payment_reference=payment_reference or "",
            booking_id=booking_id,
            attach_receipt_pdf=bool(attach_receipt_pdf),
            created_by=created_by if getattr(created_by, "pk", None) else None,
            status=EmailLog.Status.PENDING,
        )
        # Direct delivery: the delivery helper performs the SMTP handshake and
        # records the real outcome on the row (SENDING → SENT / FAILED). A
        # single honest attempt is made per click/event — unexpected errors are
        # still recorded, never raised into the business flow.
        try:
            deliver_email_log(row.pk, allow_retry=False)
        except Exception as exc:  # noqa: BLE001 - record truthfully, never propagate
            logger.error(
                "Email delivery for EmailLog#%s raised unexpectedly: %s",
                row.pk, exc.__class__.__name__,
            )
            EmailLog.objects.filter(pk=row.pk).exclude(
                status__in=[EmailLog.Status.SENT, EmailLog.Status.FAILED]
            ).update(
                status=EmailLog.Status.FAILED,
                error_class=exc.__class__.__name__,
                error_message="Delivery failed before a result could be recorded.",
                failure_stage=EmailLog.FailureStage.SMTP,
                failed_at=timezone.now(),
            )
        # Reflect the real outcome on the instance handed back to the caller
        # (delivery updates the row in the database, not this object).
        row.refresh_from_db(fields=["status", "sent_at", "failed_at", "error_class",
                                    "error_message", "failure_stage", "retry_count"])
        log = log or row
    return log


def queue_email(subject, message, recipients, **kwargs):
    """Send an email AFTER the current transaction commits.

    Kept under its historical name for the request paths (booking creation,
    payment confirmation, …) that import it, but there is NO queue anymore:
    the callback performs a full synchronous SMTP delivery (``send_email_safe``)
    as soon as the surrounding transaction commits — still inside the current
    request. When no transaction is open (autocommit), Django runs ``on_commit``
    callbacks immediately, so the email is sent straight away.

    The on-commit boundary is preserved because it guarantees a rolled-back
    booking never sends "your booking is confirmed". Delivery failures are
    recorded on the EmailLog row and never roll back business state.
    """

    def _after_commit(subject=subject, message=message, recipients=recipients, kwargs=kwargs):
        send_email_safe(subject, message, recipients, **kwargs)

    transaction.on_commit(_after_commit)
