"""End-to-end tests for the delivery-tracked receipt/email pipeline.

These cover the whole chain the bug lived in: staff triggers send → API queues a
tracked task → Celery task delivers via the email backend → EmailLog reflects
the REAL outcome (SENT / FAILED / RETRYING). Celery runs eagerly in tests so the
"worker" executes inline; SMTP is mocked so no real mail leaves the machine.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.notifications.models import EmailLog
from apps.payments.models import Payment

from .base import BaseAPITestCase
from .factories import (
    hotel_settings,
    make_booking,
    make_guest,
    make_room,
    make_room_type,
    make_staff,
    make_user,
)


class ReceiptEmailTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        hotel_settings(hotel_name="J-ONE HOTEL & LODGE", phone="0800", email="hotel@jone.test")
        self.staff = make_staff("recept@jone.test", role=User.Role.RECEPTIONIST)
        self.rt = make_room_type(name="Deluxe", price="25000.00")
        self.room = make_room(self.rt, 101)
        self.guest = make_guest(email="guest@example.com")
        self.booking = make_booking(
            self.guest, self.rt, rooms=[self.room],
            status=Booking.Status.CONFIRMED, amount_paid="25000.00", total="25000.00",
        )
        self._add_success_payment()

    def _add_success_payment(self, ref="J1P-REC-0001"):
        return Payment.objects.create(
            booking=self.booking, reference=ref, amount=Decimal("25000.00"),
            currency="NGN", status=Payment.Status.SUCCESS, provider="PAYSTACK",
            paid_at=timezone.now(),
        )

    def _url(self):
        return f"/api/admin/bookings/{self.booking.booking_reference}/send-receipt/"

    # -- Happy path ---------------------------------------------------------
    def test_send_receipt_delivers_and_marks_sent(self):
        self.auth(self.staff)
        res = self.client.post(self._url())
        # Eager mode: task ran inline, so the real outcome is SENT (HTTP 200).
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["status"], EmailLog.Status.SENT)
        self.assertEqual(res.data["data"]["recipient"], "guest@example.com")

        log = EmailLog.objects.get(pk=res.data["data"]["email_log_id"])
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.kind, EmailLog.Kind.RECEIPT)
        self.assertIsNotNone(log.sent_at)

        # Email actually reached the backend, with the PDF attached.
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("guest@example.com", msg.to)
        self.assertIn(self.booking.booking_reference, msg.subject)
        self.assertEqual(len(msg.attachments), 1)
        fname, content, mimetype = msg.attachments[0]
        self.assertTrue(fname.endswith(".pdf"))
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content[:5] == b"%PDF-")  # valid PDF header

    def test_receipt_contains_correct_details(self):
        self.auth(self.staff)
        self.client.post(self._url())
        body = mail.outbox[0].body
        self.assertIn(self.booking.booking_reference, body)
        self.assertIn("Ada Obi", body)
        self.assertIn("Deluxe", body)

    # -- Failure surfaces truthfully ---------------------------------------
    def test_smtp_failure_marks_failed_and_returns_502(self):
        self.auth(self.staff)
        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=__import__("smtplib").SMTPAuthenticationError(535, b"bad creds"),
        ):
            res = self.client.post(self._url())
        self.assertEqual(res.status_code, 502, res.data)
        self.assertFalse(res.data["success"])
        log = EmailLog.objects.filter(booking_reference=self.booking.booking_reference).latest("id")
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.error_class, "SMTPAuthenticationError")
        self.assertIn("authentication", log.error_message.lower())
        # No secret leaked into the stored reason.
        self.assertNotIn("bad creds", log.error_message)
        self.assertEqual(len(mail.outbox), 0)

    def test_transient_failure_schedules_retry_not_false_success(self):
        """A transient SMTP failure must NEVER be reported as sent.

        In eager mode Celery schedules exactly one retry (it does not loop
        without a real worker), so the truthful outcome is RETRYING + HTTP 202
        ("delivery being processed") — the row is not SENT and the guest-facing
        UI is not told the email was delivered.
        """
        self.auth(self.staff)
        import smtplib
        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPServerDisconnected("connection dropped"),
        ):
            res = self.client.post(self._url())
        log = EmailLog.objects.filter(booking_reference=self.booking.booking_reference).latest("id")
        self.assertIn(log.status, (EmailLog.Status.RETRYING, EmailLog.Status.FAILED))
        self.assertNotEqual(log.status, EmailLog.Status.SENT)
        self.assertNotEqual(res.data["data"]["status"], EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 0)
        self.assertGreaterEqual(log.retry_count, 1)

    def test_transient_failure_exhausts_retries_to_failed(self):
        """Direct check that repeated transient failures end at FAILED (what a
        real worker does across its retry attempts)."""
        import smtplib
        from apps.notifications.tasks import deliver_email_log, _RetryRequested

        log = EmailLog.objects.create(
            to_email="guest@example.com", subject="s", body="b",
            kind=EmailLog.Kind.RECEIPT, max_retries=2,
        )
        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPServerDisconnected("x"),
        ):
            # Attempts 1 & 2: transient, retry requested.
            for _ in range(2):
                with self.assertRaises(_RetryRequested):
                    deliver_email_log(log.pk, allow_retry=True)
            # Retries exhausted → FAILED, no more retry.
            result = deliver_email_log(log.pk, allow_retry=True)
        self.assertEqual(result, EmailLog.Status.FAILED)
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)

    def test_permanent_failure_does_not_retry(self):
        import smtplib
        from apps.notifications.tasks import deliver_email_log

        log = EmailLog.objects.create(
            to_email="guest@example.com", subject="s", body="b", max_retries=3,
        )
        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"x"),
        ):
            result = deliver_email_log(log.pk, allow_retry=True)
        self.assertEqual(result, EmailLog.Status.FAILED)  # permanent → no RETRYING

    # -- Guard rails --------------------------------------------------------
    def test_missing_guest_email_rejected(self):
        self.guest.email = ""
        self.guest.save()
        self.auth(self.staff)
        res = self.client.post(self._url())
        self.assertEqual(res.status_code, 400)
        self.assertEqual(EmailLog.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_guest_email_rejected(self):
        self.guest.email = "not-an-email"
        self.guest.save()
        self.auth(self.staff)
        res = self.client.post(self._url())
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_unauthorized_cannot_send(self):
        guest_user = make_user(email="randomguest@example.com", role=User.Role.GUEST)
        self.auth(guest_user)
        res = self.client.post(self._url())
        self.assertIn(res.status_code, (401, 403))
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_unauthenticated_cannot_send(self):
        self.unauth()
        res = self.client.post(self._url())
        self.assertIn(res.status_code, (401, 403))

    # -- Status visibility --------------------------------------------------
    def test_email_log_status_endpoint(self):
        self.auth(self.staff)
        res = self.client.post(self._url())
        log_id = res.data["data"]["email_log_id"]
        detail = self.client.get(f"/api/notifications/emails/{log_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["status"], EmailLog.Status.SENT)

    def test_email_log_list_filter_failed(self):
        self.auth(self.staff)
        import smtplib
        with mock.patch(
            "apps.notifications.tasks.EmailMessage.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"x"),
        ):
            self.client.post(self._url())
        res = self.client.get("/api/notifications/emails/?status=FAILED")
        self.assertEqual(res.status_code, 200)
        rows = res.data["data"]
        # Envelope may nest under 'data' or be a list depending on pagination.
        items = rows if isinstance(rows, list) else rows.get("results", rows)
        self.assertTrue(any(r["status"] == "FAILED" for r in items))


class EmailPipelineUnitTests(BaseAPITestCase):
    """Lower-level guarantees of the central pipeline used by ALL emails."""

    def test_send_email_safe_creates_log_and_sends(self):
        from apps.core.emails import send_email_safe

        log = send_email_safe("Hi", "Body", ["a@example.com"], kind="GENERIC")
        self.assertIsNotNone(log)
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_send_email_safe_skips_invalid_recipient(self):
        from apps.core.emails import send_email_safe

        self.assertIsNone(send_email_safe("Hi", "Body", ["bad"], kind="GENERIC"))
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_already_sent_is_idempotent(self):
        from apps.notifications.tasks import deliver_email_log

        log = EmailLog.objects.create(
            to_email="a@example.com", subject="s", body="b",
            status=EmailLog.Status.SENT, sent_at=timezone.now(),
        )
        result = deliver_email_log(log.pk)
        self.assertEqual(result, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 0)  # not re-sent
