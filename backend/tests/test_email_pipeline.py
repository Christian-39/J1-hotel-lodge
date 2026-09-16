"""Tests for the synchronous, truth-tracking email dispatch pipeline.

Covers the current architecture (email queue removed):

* booking-path emails are only dispatched AFTER the surrounding transaction
  commits (a rolled-back booking sends nothing);
* delivery is a direct SMTP attempt from the calling process — no Celery task,
  no broker, no Redis, in ANY environment (eager or not);
* EmailLog always reflects the REAL outcome: SENT only after the mail backend
  accepted the message, FAILED (with stage + credential-free reason) otherwise;
* SMTP failures never raise into the business flow.
"""
from unittest import mock

from django.core import mail
from django.test import override_settings, TestCase

from apps.core.emails import queue_email, send_email_safe
from apps.notifications.models import EmailLog


class QueueEmailCommitSemanticsTests(TestCase):
    """queue_email must defer to the surrounding transaction's commit."""

    def test_rolled_back_transaction_sends_nothing(self):
        from django.db import transaction

        with transaction.atomic():
            queue_email(
                "Subject", "Body", ["guest@example.com"], kind="BOOKING_PENDING"
            )
            transaction.set_rollback(True)
        self.assertEqual(EmailLog.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_committed_transaction_delivers_synchronously(self):
        from django.db import transaction

        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                queue_email(
                    "Complete your booking", "Body", ["guest@example.com"],
                    kind="BOOKING_PENDING", booking_reference="J1-TEST-2",
                )
        log = EmailLog.objects.get(booking_reference="J1-TEST-2")
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

class SynchronousDeliveryTests(TestCase):
    """Direct delivery: in-process SMTP, no broker, one honest attempt."""

    def test_send_email_safe_delivers_and_records_sent(self):
        log = send_email_safe(
            "Subject", "Body text", ["guest@example.com"], kind="GENERIC"
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_transient_failure_fails_honestly(self):
        # One attempt on the request path: a transient failure must end FAILED
        # (never SENT, never a queue state that nothing will resolve).
        import smtplib

        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPServerDisconnected("drop"),
        ):
            log = send_email_safe(
                "Subject", "Body", ["guest@example.com"], kind="GENERIC"
            )
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.failure_stage, EmailLog.FailureStage.SMTP)
        self.assertEqual(log.retry_count, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_permanent_failure_recorded_without_secret_leak(self):
        import smtplib

        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"super-secret-password"),
        ):
            log = send_email_safe(
                "Subject", "Body", ["guest@example.com"], kind="GENERIC"
            )
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.error_class, "SMTPAuthenticationError")
        self.assertNotIn("super-secret-password", log.error_message)

    def test_delivery_never_touches_celery(self):
        # The email queue is gone: nothing named like the old task may exist,
        # and delivery must not go near any broker machinery.
        import apps.notifications.tasks as tasks_module

        self.assertFalse(hasattr(tasks_module, "send_email_task"))
        with mock.patch(
            "apps.notifications.tasks.deliver_email_log", wraps=tasks_module.deliver_email_log
        ) as spy:
            log = send_email_safe(
                "Subject", "Body", ["guest@example.com"], kind="GENERIC"
            )
        spy.assert_called_once_with(log.pk, allow_retry=False)
        self.assertEqual(log.status, EmailLog.Status.SENT)


class ProductionModeSynchronousTests(TestCase):
    """With eager mode OFF (the production flag combination) email is STILL
    delivered synchronously — the broker is no longer consulted for email."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False, CELERY_BROKER_URL="redis://invalid-host:6399/0")
    def test_delivery_is_synchronous_and_needs_no_broker(self):
        # An unreachable broker would raise the moment anything tried to use
        # it; delivery here succeeds precisely because email ignores Celery.
        log = send_email_safe(
            "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(log.task_id, "")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_smtp_failure_marks_failed_not_queued(self):
        import smtplib

        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPConnectError(421, "nope"),
        ):
            log = send_email_safe(
                "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
            )
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.failure_stage, EmailLog.FailureStage.SMTP)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_failure_does_not_raise_to_the_api_caller(self):
        import smtplib

        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=OSError("network down"),
        ):
            log = send_email_safe(
                "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
            )
        self.assertIsNotNone(log)  # returned normally, failure recorded on row
        self.assertEqual(log.status, EmailLog.Status.FAILED)


class DevelopmentCelerySettingsTests(TestCase):
    """The development environment must not require Redis in any form."""

    def test_development_settings_have_no_redis_dependency(self):
        from django.conf import settings

        # Eager in-process execution with no broker/result backend at all.
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)
        self.assertIsNone(settings.CELERY_RESULT_BACKEND)
        self.assertEqual(settings.CELERY_BROKER_URL, "memory://")
        self.assertFalse(settings.CELERY_TASK_STORE_EAGER_RESULT)

    def test_development_forces_eager_even_when_env_var_says_otherwise(self):
        # The eager contract is hard-coded for development — a stray
        # CELERY_TASK_ALWAYS_EAGER=False in a local .env must NOT resurrect the
        # Redis connection-retry loop this architecture removed.
        import importlib
        import os

        with mock.patch.dict(os.environ, {"CELERY_TASK_ALWAYS_EAGER": "False"}):
            import config.settings.development as dev

            importlib.reload(dev)
            try:
                self.assertTrue(dev.CELERY_TASK_ALWAYS_EAGER)
                self.assertIsNone(dev.CELERY_RESULT_BACKEND)
                self.assertEqual(dev.CELERY_BROKER_URL, "memory://")
            finally:
                importlib.reload(dev)  # restore the original module state
