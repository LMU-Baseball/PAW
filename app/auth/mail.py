"""Outbound account email (verify address, password reset).

Backend chosen by PAW_MAIL_BACKEND, read live so an env change needs no code
change:

- "smtp"    -- send through PAW_SMTP_HOST/PORT/USER/PASSWORD. Built for AWS SES's
               SMTP endpoint (email-smtp.<region>.amazonaws.com:587), but any
               STARTTLS SMTP server works. Stdlib only, no boto3 dependency.
- "console" -- don't send; log the message and keep it in `outbox`. For local
               dev, so the flows can be clicked through without SES.
- unset     -- email is off: registration auto-verifies (the pre-email
               behavior) and forgot-password tells the user to ask a coach. This
               is what keeps a deploy safe before SES is actually set up.
"""
from __future__ import annotations

import logging
import os
import smtplib
from collections import deque
from email.message import EmailMessage

log = logging.getLogger(__name__)

outbox: deque[EmailMessage] = deque(maxlen=50)


def _backend() -> str:
    return (os.getenv("PAW_MAIL_BACKEND") or "").strip().lower()


def mail_enabled() -> bool:
    return _backend() in ("smtp", "console")


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns False (and logs) on failure rather than
    raising, so a mail outage degrades to a flash message, not a 500."""
    backend = _backend()
    msg = EmailMessage()
    msg["From"] = os.getenv("PAW_MAIL_FROM") or "noreply@lmubaseball.com"
    msg["To"] = to
    msg["Subject"] = subject
    reply_to = (os.getenv("PAW_MAIL_REPLY_TO") or "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    if backend == "console":
        outbox.append(msg)
        log.warning("PAW_MAIL_BACKEND=console -- email not sent:\n%s", msg)
        return True
    if backend != "smtp":
        return False
    try:
        host = os.environ["PAW_SMTP_HOST"]
        port = int(os.getenv("PAW_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            user = os.getenv("PAW_SMTP_USER")
            if user:
                smtp.login(user, os.getenv("PAW_SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("Failed to send email to %s", to)
        return False
