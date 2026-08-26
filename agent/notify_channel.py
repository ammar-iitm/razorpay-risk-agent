"""
agent/notify_channel.py — real merchant notification channel (Day 8),
replacing tool_notify_merchant's old "# TODO (Day 8): actually send via
WhatsApp/email provider" stub.

Email, not WhatsApp: the tracker's own Day 8 plan says "email is fine —
document if it's stubbed," and email needs no third-party account beyond
credentials this project's build already assumes access to (Gmail SMTP
with an app password, or any other SMTP provider) — a WhatsApp Business
API integration is a real vendor onboarding process, not a few lines of
stdlib code, and isn't worth the scope for what this tool needs to prove.

Uses Python's built-in smtplib — zero new dependencies, same reasoning as
day2/webhook_verify.py staying stdlib-only. Soft-optional, same pattern as
agent/razorpay_client.py: without SMTP_* env vars configured, this honestly
reports itself as stubbed rather than pretending to send, and
tool_notify_merchant's own tool_output/agent_reasoning says so explicitly —
"stubbed" is a real, load-bearing state here, not a bug to hide.

Env vars (all required together, or none — no partial config):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, MERCHANT_EMAIL_TO
"""

import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional

_REQUIRED_VARS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "MERCHANT_EMAIL_TO"]


def email_configured() -> bool:
    return all(os.environ.get(v) for v in _REQUIRED_VARS)


def send_merchant_email(subject: str, body: str) -> dict:
    """Attempts a real SMTP send. Returns
    {"sent": bool, "channel": "email", "detail": str} — 'sent' is only ever
    True after a real SMTP session actually completes without error.
    Any failure (missing config, auth failure, network error, timeout)
    returns sent=False with a human-readable reason in 'detail', never
    raises — a notification failing shouldn't take down the tool call that
    triggered it, but it also shouldn't be reported as having succeeded."""
    if not email_configured():
        missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
        return {"sent": False, "channel": "email", "detail": f"stubbed — not configured (missing: {', '.join(missing)})"}

    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ["SMTP_FROM"]
    recipient = os.environ["MERCHANT_EMAIL_TO"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(sender, [recipient], msg.as_string())
        return {"sent": True, "channel": "email", "detail": f"sent to {recipient}"}
    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        return {"sent": False, "channel": "email", "detail": f"send failed: {e}"}
