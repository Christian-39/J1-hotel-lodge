"""Diagnose real SMTP delivery end-to-end.

Unlike the application's normal path (which reports SENT once the SMTP server
returns 250 OK), this command prints the FULL SMTP conversation — including the
server's final acceptance line, which for Gmail contains a queue id such as::

    250 2.0.0 OK  1699999999 abc123 - gsmtp

That queue id is proof the message was accepted into Gmail's delivery system.
If you see it, the problem is downstream filtering (Spam/Promotions/alias
mismatch), not the application. If you get an exception instead, the reason is
printed so you can fix the configuration.

Usage:
    python manage.py smtp_check recipient@example.com

Security: the password is NEVER printed (only whether one is set and its
length). Nothing here logs credentials.
"""
import smtplib
import socket
import ssl
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a diagnostic email and print the full SMTP conversation."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Where to send the test email.")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        host = settings.EMAIL_HOST
        port = settings.EMAIL_PORT
        user = settings.EMAIL_HOST_USER
        password = settings.EMAIL_HOST_PASSWORD
        use_tls = getattr(settings, "EMAIL_USE_TLS", False)
        use_ssl = getattr(settings, "EMAIL_USE_SSL", False)
        from_email = settings.DEFAULT_FROM_EMAIL
        timeout = getattr(settings, "EMAIL_TIMEOUT", 20) or 20

        self.stdout.write(self.style.MIGRATE_HEADING("Resolved email settings"))
        self.stdout.write(f"  EMAIL_BACKEND      : {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST         : {host!r}")
        self.stdout.write(f"  EMAIL_PORT         : {port}")
        self.stdout.write(f"  EMAIL_USE_TLS      : {use_tls}")
        self.stdout.write(f"  EMAIL_USE_SSL      : {use_ssl}")
        self.stdout.write(f"  EMAIL_HOST_USER    : {'configured' if user else 'NOT SET'}")
        self.stdout.write(
            f"  EMAIL_HOST_PASSWORD: {'configured' if password else 'NOT SET'}"
        )
        self.stdout.write(f"  DEFAULT_FROM_EMAIL : {from_email!r}")
        self.stdout.write(f"  recipient          : {recipient!r}")

        # Deliverability warning without echoing the SMTP login credential.
        if user and user.lower() not in (from_email or "").lower():
            self.stdout.write(self.style.WARNING(
                "\n  ⚠ DEFAULT_FROM_EMAIL does not match EMAIL_HOST_USER.\n"
                "    Ensure DEFAULT_FROM_EMAIL is a sender verified by the SMTP provider."
            ))

        if "console" in settings.EMAIL_BACKEND:
            raise CommandError(
                "EMAIL_BACKEND is the console backend — mail is only printed, never "
                "delivered. Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend "
                "in your .env to test real delivery."
            )
        if not host:
            raise CommandError("EMAIL_HOST is empty — nothing to connect to.")

        msg = MIMEText("This is a J-ONE HOTEL & LODGE SMTP diagnostic test message.")
        msg["Subject"] = "J-ONE SMTP diagnostic — Payment receipt test"
        msg["From"] = from_email
        msg["To"] = recipient
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jone-hotel")

        self.stdout.write(self.style.MIGRATE_HEADING("\nSMTP conversation (debug)"))
        try:
            if use_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
            else:
                server = smtplib.SMTP(host, port, timeout=timeout)
            server.ehlo()
            if use_tls and not use_ssl:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            # SECURITY: enable the wire debug ONLY around the non-credential
            # parts of the conversation. The AUTH exchange base64-encodes the
            # username + password, so it must never be printed (a pasted log
            # would otherwise leak the SMTP credentials).
            if user:
                server.set_debuglevel(0)
                server.login(user, password)
            server.set_debuglevel(1)  # mail/rcpt/data only — no credentials here
            # sendmail returns {} when every recipient was accepted.
            refused = server.sendmail(self._addr(from_email), [recipient], msg.as_string())
            server.set_debuglevel(0)
            server.quit()
        except socket.gaierror:
            raise CommandError("SMTP DNS FAILURE: EMAIL_HOST could not be resolved.") from None
        except (TimeoutError, socket.timeout):
            raise CommandError("SMTP CONNECTION TIMEOUT: the server did not respond in time.") from None
        except ssl.SSLError as exc:
            raise CommandError(f"SMTP TLS FAILURE: {exc.__class__.__name__}.") from None
        except smtplib.SMTPAuthenticationError as exc:
            raise CommandError(
                "SMTP AUTHENTICATION FAILURE: credentials were rejected (server code "
                f"{exc.smtp_code}). Gmail requires an App Password; Brevo requires an SMTP key."
            ) from None
        except smtplib.SMTPSenderRefused as exc:
            raise CommandError(
                f"SMTP SENDER REJECTED: verify DEFAULT_FROM_EMAIL (server code {exc.smtp_code})."
            ) from None
        except smtplib.SMTPRecipientsRefused:
            raise CommandError("SMTP RECIPIENT REJECTED: the server rejected the test recipient.") from None
        except smtplib.SMTPResponseException as exc:
            raise CommandError(f"SMTP SERVER RESPONSE: rejected with code {exc.smtp_code}.") from None
        except (ConnectionRefusedError, ConnectionError) as exc:
            raise CommandError(f"SMTP CONNECTION FAILURE: {exc.__class__.__name__}.") from None
        except Exception as exc:  # noqa: BLE001
            # Exception text may contain provider details or credentials; only
            # the class is safe to paste into a support ticket.
            raise CommandError(f"SMTP FAILURE: {exc.__class__.__name__}.") from None

        if refused:
            raise CommandError(f"Server refused the recipient(s): {refused}")

        self.stdout.write(self.style.SUCCESS(
            "\n✅ SMTP server ACCEPTED the message.\n"
            "   Look above for the final '250 ... - gsmtp' line — that queue id is\n"
            "   Gmail's proof of acceptance.\n"
            f"   Now check {recipient}: Inbox, then Spam, Promotions/Updates tabs,\n"
            "   and search  in:anywhere subject:(J-ONE SMTP diagnostic)\n"
            f"   Also check the SENT/All Mail folder of {user}."
        ))
        self.stdout.write(f"   Message-ID: {msg['Message-ID']}")

    @staticmethod
    def _addr(value):
        from email.utils import parseaddr

        return parseaddr(value)[1] or value
