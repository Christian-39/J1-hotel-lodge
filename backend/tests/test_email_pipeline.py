"""Tests for the non-blocking, truth-tracking email dispatch pipeline.

Covers the architecture introduced to fix the booking-timeout bug:

* booking-path emails are only dispatched AFTER the booking transaction
  commits (a rolled-back booking sends nothing);
* eager development never touches Redis (no broker, no result backend);
* a broker failure in production mode is recorded as FAILED/BROKER and is
  NEVER papered over with a synchronous SMTP send from the request path;
* eager delivery makes exactly one honest attempt and records the outcome.
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

    def test_committed_transaction_delivers_inline_in_test_mode(self):
        from django.db import transaction

        with override_settings(EMAIL_EAGER_INLINE=True):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    queue_email(
                        "Complete your booking", "Body", ["guest@example.com"],
                        kind="BOOKING_PENDING", booking_reference="J1-TEST-2",
                    )
        log = EmailLog.objects.get(booking_reference="J1-TEST-2")
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)


class EagerDispatchTests(TestCase):
    """Eager mode: in-process delivery, no broker/result backend, one attempt."""

    def test_send_email_safe_delivers_inline_and_records_sent(self):
        log = send_email_safe(
            "Subject", "Body text", ["guest@example.com"], kind="GENERIC"
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_eager_transient_failure_fails_honestly_no_retrying_limbo(self):
        # Eager mode makes ONE attempt: there is no worker to honour RETRYING,
        # so a transient failure must end FAILED (never a permanent RETRYING
        # row that nothing will ever pick up).
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

    def test_eager_mode_never_touches_the_broker(self):
        # In eager mode send_email_safe must not import/consult any broker:
        # simulating a completely absent broker proves Redis is unnecessary.
        from django.conf import settings

        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)
        with mock.patch(
            "apps.notifications.tasks.send_email_task.delay",
            side_effect=AssertionError("delay() must not be used in eager mode"),
        ):
            log = send_email_safe(
                "Subject", "Body", ["guest@example.com"], kind="GENERIC"
            )
        self.assertEqual(log.status, EmailLog.Status.SENT)


class ProductionDispatchTests(TestCase):
    """Production (non-eager) mode: broker publish, honest queue failure."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_successful_queue_marks_queued_not_sent(self):
        with mock.patch(
            "apps.notifications.tasks.send_email_task.delay"
        ) as delay:
            delay.return_value = type("R", (), {"id": "task-123"})()
            log = send_email_safe(
                "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
            )
        delay.assert_called_once_with(log.pk)
        log.refresh_from_db()
        # QUEUED — never reported as SENT before SMTP has accepted anything.
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(log.task_id, "task-123")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_broker_failure_records_failed_broker_without_sync_send(self):
        with mock.patch(
            "apps.notifications.tasks.send_email_task.delay",
            side_effect=ConnectionRefusedError("redis down"),
        ):
            log = send_email_safe(
                "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
            )
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.failure_stage, EmailLog.FailureStage.BROKER)
        self.assertEqual(log.error_class, "ConnectionRefusedError")
        # The dangerous old behaviour — falling back to a synchronous SMTP
        # send from the request path — must NOT happen.
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_broker_failure_does_not_raise_to_the_api_caller(self):
        with mock.patch(
            "apps.notifications.tasks.send_email_task.delay",
            side_effect=ConnectionRefusedError("redis down"),
        ):
            log = send_email_safe(
                "Receipt", "Body", ["guest@example.com"], kind="RECEIPT"
            )
        self.assertIsNotNone(log)  # returned normally, failure recorded on row


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
