"""
agent/razorpay_client.py — thin wrapper around Razorpay's Payments API,
used by agent_tools.py's tool_hold_payment / tool_release_payment for live
status verification (Day 7).

Deliberately SOFT-FAILS rather than raising or exiting when credentials
aren't configured — unlike day2/create_test_order.py's _check_env(), which
correctly refuses to run at all for a standalone script, this module is
imported by agent_tools.py, which must keep working with ZERO external
dependencies for `--demo` and the offline test/verification patterns used
throughout Days 1-6. A missing env var or unreachable API here means "skip
live verification and fall back to the local record," never a crash.
"""

import os
from typing import Optional

try:
    import requests
except ImportError:
    requests = None

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")


def credentials_configured() -> bool:
    return bool(requests and KEY_ID and KEY_SECRET and KEY_ID.startswith("rzp_test_"))


def fetch_payment(payment_id: str) -> Optional[dict]:
    """Fetch a payment's LIVE status from Razorpay's test-mode API.

    Returns None if credentials aren't configured, `requests` isn't
    installed, the payment_id isn't real-looking, the payment doesn't
    exist, or the request fails for any reason. Callers must treat None as
    "live verification unavailable," not as an error — a demo run using
    fake payment ids (pay_demo_...) should keep working exactly as before,
    with no credentials and no network required.
    """
    if not credentials_configured():
        return None
    if not payment_id or not payment_id.startswith("pay_"):
        return None
    try:
        resp = requests.get(
            f"https://api.razorpay.com/v1/payments/{payment_id}",
            auth=(KEY_ID, KEY_SECRET),
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.RequestException:
        return None
