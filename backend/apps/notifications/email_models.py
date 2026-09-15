"""Delivery-tracked email log.

Every transactional email (receipts, booking confirmations, cancellations,
password resets, enquiry/staff alerts) is recorded here BEFORE it is handed to
the email backend, and the row is updated as the Celery worker actually
processes it. This is what makes the difference between "we queued a task" and
"the guest's mail server accepted the message" visible to staff — the bug this
model exists to kill was the dashboard reporting success while the worker
silently failed to deliver.

No secrets are ever stored here: SMTP credentials, API keys, tokens and
passwords must never be written to ``error_message`` or any other field.
"""
from django.conf import settings
from django.db import models


class EmailLog(models.Model):
    """One transactional email and its real delivery lifecycle."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"        # row created, not yet queued
        QUEUED = "QUEUED", "Queued"           # Celery task accepted the job
        SENDING = "SENDING", "Sending"        # worker is talking to SMTP now
        SENT = "SENT", "Sent"                 # SMTP accepted the message
        FAILED = "FAILED", "Failed"           # permanent / retries exhausted
        RETRYING = "RETRYING", "Retrying"     # transient failure, will retry

    class FailureStage(models.TextChoices):
        """WHERE in the pipeline a FAILED/RETRYING email broke.

        This makes an admin able to tell, at a glance, whether the receipt
        never rendered (a code/data bug), the PDF could not be generated, or the
        SMTP server rejected the message (a delivery/config problem) — instead
        of guessing from a generic error string.
        """
        NONE = "", "—"
        RENDER = "RENDER", "Rendering the receipt"
        ATTACHMENT = "ATTACHMENT", "Generating the PDF attachment"
        SMTP = "SMTP", "Submitting to the mail server"

    class Kind(models.TextChoices):
        RECEIPT = "RECEIPT", "Payment receipt"
        BOOKING_CONFIRMATION = "BOOKING_CONFIRMATION", "Booking confirmation"
        BOOKING_PENDING = "BOOKING_PENDING", "Booking pending / complete payment"
        CANCELLATION = "CANCELLATION", "Cancellation"
        REFUND = "REFUND", "Refund"
        PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
        ENQUIRY = "ENQUIRY", "Enquiry / staff alert"
        REVIEW_INVITE = "REVIEW_INVITE", "Review invitation"
        GENERIC = "GENERIC", "Generic"

    # --- Envelope ----------------------------------------------------------
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    # Optional rich HTML alternative. When present the worker sends a proper
    # multipart/alternative message (text/plain + text/html); when blank the
    # message stays a single text/plain part exactly as before. Storing it here
    # keeps the worker the single source of truth for what actually gets sent.
    html_body = models.TextField(blank=True, default="")
    kind = models.CharField(
        max_length=32, choices=Kind.choices, default=Kind.GENERIC, db_index=True
    )

    # --- Context (stable identifiers, never large serialized objects) ------
    booking_reference = models.CharField(max_length=80, blank=True, default="", db_index=True)
    payment_reference = models.CharField(max_length=120, blank=True, default="")
    # For attachment regeneration by the worker (source of truth is the DB row,
    # never a file the browser produced).
    booking_id = models.PositiveBigIntegerField(null=True, blank=True)
    attach_receipt_pdf = models.BooleanField(default=False)

    # --- Lifecycle ---------------------------------------------------------
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=3)
    task_id = models.CharField(max_length=255, blank=True, default="")
    error_class = models.CharField(max_length=120, blank=True, default="")
    # Human-readable, credential-free reason (safe to surface to admins).
    error_message = models.TextField(blank=True, default="")
    # WHERE the failure happened (render / attachment / SMTP). Empty when the
    # email has not failed. Lets staff distinguish a receipt that never rendered
    # from one the mail server rejected.
    failure_stage = models.CharField(
        max_length=16, choices=FailureStage.choices, blank=True, default=""
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_emails",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["kind", "status"]),
            models.Index(fields=["booking_reference", "status"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.kind} -> {self.to_email}"

    @property
    def is_terminal(self):
        return self.status in (self.Status.SENT, self.Status.FAILED)
