"""Re-deliver tracked emails that failed (operational recovery tool).

Email delivery is synchronous — there is no broker any more — so "re-queueing"
simply drives another direct SMTP delivery attempt for each selected row,
right here in this process:

    python manage.py requeue_emails            # BROKER-era failures only
    python manage.py requeue_emails --all      # any non-terminal failure

Rows already SENT are never touched, so the command can never double-deliver
a message. The historical ``--all``/BROKER filters are kept so runbooks keep
working; rows that once failed with failure_stage=BROKER (from the retired
queue architecture) are simply delivered now.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import EmailLog


class Command(BaseCommand):
    help = "Re-deliver EmailLog rows that failed previously (direct, synchronous delivery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true",
            help="Re-deliver every FAILED email, not only BROKER-stage failures.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Only report what would be re-delivered.",
        )

    def handle(self, *args, **options):
        from apps.notifications.tasks import deliver_email_log

        qs = EmailLog.objects.filter(status=EmailLog.Status.FAILED)
        if not options["all"]:
            qs = qs.filter(failure_stage=EmailLog.FailureStage.BROKER)
        rows = list(qs.order_by("id"))
        if not rows:
            self.stdout.write("No failed emails to re-deliver.")
            return

        self.stdout.write(f"Re-delivering {len(rows)} email(s)...")
        delivered = 0
        for log in rows:
            if options["dry_run"]:
                self.stdout.write(f"  [dry-run] EmailLog#{log.pk} {log.kind} -> {log.to_email}")
                continue
            EmailLog.objects.filter(pk=log.pk).update(
                status=EmailLog.Status.PENDING,
                error_class="",
                error_message="",
                failure_stage="",
                failed_at=None,
                retry_count=0,
            )
            try:
                deliver_email_log(log.pk, allow_retry=False)
            except Exception as exc:  # noqa: BLE001 - outcome is on the row
                self.stdout.write(
                    f"  EmailLog#{log.pk} delivery raised {exc.__class__.__name__} (see row)"
                )
            log.refresh_from_db()
            self.stdout.write(
                f"  EmailLog#{log.pk} {log.kind} -> {log.to_email}: {log.status}"
            )
            delivered += 1
        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {len(rows)} email(s) would be re-delivered.")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Re-delivered {delivered} email(s) at {timezone.now():%Y-%m-%d %H:%M} UTC.")
            )
