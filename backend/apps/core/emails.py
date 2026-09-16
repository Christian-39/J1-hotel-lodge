"""Transactional email delivery with real, tracked lifecycle.

The rules this module enforces:

1. An API request may report that an email was **queued**, but it must NEVER
   report "sent" for work that has only been placed on a queue. Actual
   delivery is performed by the Celery worker (production) or an in-process
   background thread (eager development), and the outcome is recorded on a
   persistent ``EmailLog`` row (PENDING → QUEUED → SENDING → SENT / FAILED /
   RETRYING) so staff can see whether a message truly left the system.
2. Email delivery must NEVER block an API response. Booking/payment requests
   queue through :func:`queue_email`, which runs strictly AFTER the database
   transaction commits (``transaction.on_commit``) and — in eager development
   mode — hands the actual SMTP work to a daemon thread. A slow or unreachable
   SMTP server can therefore never turn a successful booking into a
   client-side timeout (the exact failure this architecture fixed).
3. A broker/queue failure is RECORDED (EmailLog FAILED, failure_stage=BROKER)
   and reported — it is never papered over with a synchronous SMTP send from
   the request path, because that could block the API for tens of seconds and
   is exactly the dangerous fallback that used to exist.

Application operational emails (booking confirmations, cancellation requests,
refund lifecycle notices, staff alerts, password resets, payment receipts) all
go through here so the behaviour is central, not receipt-only.

Security: SMTP credentials, API keys, tokens and passwords are NEVER logged or
stored on the EmailLog. Only the exception class and a scrubbed, human-readable
reason are persisted.
"""
import logging
import threading
from email.utils import parseaddr

from django.conf import settings
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
    direct=False,
):
    """Record + dispatch a transactional email; returns its EmailLog row.

    ``message`` is the required plain-text body (also the fallback for clients
    that cannot render HTML). ``html_message`` is an optional styled HTML
    alternative — when supplied the delivery builds a proper
    ``multipart/alternative`` message, never HTML-as-escaped-text.

    How the row is dispatched depends on the environment:

    * eager (development/tests): delivered IN-PROCESS by calling
      ``deliver_email_log`` directly. No broker and no result backend are ever
      contacted — that is what makes Redis unnecessary locally. One honest
      attempt is made (no Celery retry machinery: an eager retry would re-run
      inline with no countdown and no worker exists to honour RETRYING).
    * production: ``send_email_task.delay()`` publishes to the broker and the
      row moves to QUEUED. If the broker is unreachable the row becomes FAILED
      with failure_stage=BROKER so staff can see it and re-send; the API
      request is never blocked by a synchronous SMTP fallback.

    Errors never propagate to the API caller — but they are never hidden
    either: every attempt is tracked on the returned EmailLog row.
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
            html_body=html_message or "",
            kind=kind if kind in EmailLog.Kind.values else EmailLog.Kind.GENERIC,
            booking_reference=booking_reference or "",
            payment_reference=payment_reference or "",
            booking_id=booking_id,
            attach_receipt_pdf=bool(attach_receipt_pdf),
            created_by=created_by if getattr(created_by, "pk", None) else None,
            status=EmailLog.Status.PENDING,
        )
        _dispatch(row, direct=direct)
        log = log or row
    return log


def _dispatch(log, *, direct=False):
    """Hand a single EmailLog row to the worker, or deliver it in-process.

    Must only be called AFTER the row is committed (or from autocommit where
    the row is already durable) — otherwise a worker could pick up a row that
    a later rollback would delete.
    """
    from apps.notifications.models import EmailLog
    from apps.notifications.tasks import deliver_email_log, send_email_task

    if direct:
        # Staff explicitly requested an immediate send. Perform the same tracked
        # MIME/PDF/SMTP operation used by the worker, but in this HTTP request;
        # no broker, Celery task or QUEUED state is involved. With no worker to
        # honour a countdown, a transient error is truthfully terminal FAILED.
        try:
            deliver_email_log(log.pk, allow_retry=False)
        except Exception as exc:  # status is persisted by deliver_email_log
            logger.info(
                "Direct email delivery for EmailLog#%s ended with %s",
                log.pk, exc.__class__.__name__,
            )
        log.refresh_from_db(fields=["status", "sent_at", "failed_at", "error_class",
                                    "error_message", "failure_stage", "retry_count"])
        return

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        # Eager development/test path: deliver in-process, bypassing Celery's
        # broker AND result backend entirely. Failures (including transient
        # ones) are recorded as FAILED — there is no worker to retry, so
        # RETRYING would be a lie that never resolves.
        try:
            deliver_email_log(log.pk, allow_retry=False)
        except Exception as exc:  # noqa: BLE001 - status already persisted by task
            logger.info(
                "Eager email delivery for EmailLog#%s ended with %s (status already recorded)",
                log.pk, exc.__class__.__name__,
            )
        # Reflect the real outcome on the instance handed back to the caller
        # (delivery updates the row in the database, not this object).
        log.refresh_from_db(fields=["status", "sent_at", "failed_at", "error_class",
                                    "error_message", "failure_stage", "retry_count"])
        return

    # Production path: enqueue on the broker; the Celery worker performs the
    # actual SMTP delivery and records the real outcome.
    try:
        result = send_email_task.delay(log.pk)
    except Exception as exc:  # noqa: BLE001 - broker unavailable, must not propagate
        # The task NEVER ran. Record the queueing failure truthfully. There is
        # deliberately NO synchronous SMTP fallback here: sending from the API
        # request would block the response for the whole SMTP handshake (and
        # any retries), which is precisely the production hazard this pipeline
        # must avoid. Staff see FAILED/BROKER rows in the dashboard and can
        # re-send; `manage.py requeue_emails` can re-drive them after the
        # broker recovers.
        EmailLog.objects.filter(pk=log.pk).update(
            status=EmailLog.Status.FAILED,
            error_class=exc.__class__.__name__,
            error_message=(
                "The email queue is temporarily unavailable, so this email "
                "was not sent. It can be re-sent once the queue recovers."
            ),
            failure_stage=EmailLog.FailureStage.BROKER,
            failed_at=timezone.now(),
        )
        logger.error(
            "Could not queue email task for EmailLog#%s (%s); recorded as FAILED/BROKER "
            "- no synchronous fallback was attempted.",
            log.pk, exc.__class__.__name__,
        )
        return

    EmailLog.objects.filter(pk=log.pk, status=EmailLog.Status.PENDING).update(
        status=EmailLog.Status.QUEUED,
        queued_at=timezone.now(),
        task_id=getattr(result, "id", "") or "",
    )
    log.refresh_from_db(fields=["status", "queued_at", "task_id"])


def queue_email(subject, message, recipients, **kwargs):
    """Queue an email AFTER the current transaction commits (non-blocking).

    This is the variant request paths (booking creation, payment confirmation,
    …) must use. It guarantees two things ``send_email_safe`` alone cannot:

    * the email is only dispatched if the surrounding transaction actually
      COMMITS (``transaction.on_commit``) — a rolled-back booking never sends
      "your booking is confirmed";
    * the dispatch itself can never stall the HTTP response: in production it
      is a broker publish; in eager development the whole send (SMTP included)
      happens on a daemon thread.

    Tests that need deterministic in-thread delivery set
    ``EMAIL_EAGER_INLINE = True`` (see tests/base.py).
    """

    def _after_commit(subject=subject, message=message, recipients=recipients, kwargs=kwargs):
        eager = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        if not eager or getattr(settings, "EMAIL_EAGER_INLINE", False):
            # Production: a fast broker publish. Tests: deterministic inline
            # delivery. Neither can meaningfully block.
            send_email_safe(subject, message, recipients, **kwargs)
            return

        # Eager development: the full send (SMTP handshake included) runs on a
        # daemon thread so the API response is never delayed by mail delivery.
        def _deliver_with_lock_retry(attempt=0):
            try:
                send_email_safe(subject, message, recipients, **kwargs)
            except Exception as exc:  # noqa: BLE001 - delivery records its own state
                # SQLite dev databases lock for the instant another writer is
                # committing (the request threads race this one). Waiting a
                # moment and retrying is always safe on a background thread;
                # anything else is already recorded on the EmailLog row.
                name = exc.__class__.__name__
                locked = "locked" in str(exc).lower() and name == "OperationalError"
                if locked and attempt < 3:
                    threading.Timer(0.5 * (attempt + 1),
                                    lambda: _deliver_with_lock_retry(attempt + 1)).start()
                else:
                    logger.warning(
                        "Background email delivery failed permanently: %s", name
                    )

        thread = threading.Thread(
            target=_deliver_with_lock_retry,
            name=f"jone-email-{kwargs.get('kind', 'GENERIC')}",
            daemon=True,
        )
        thread.start()

    transaction.on_commit(_after_commit)
