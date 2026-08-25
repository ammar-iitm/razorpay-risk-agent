"""
day2/create_test_order.py — creates a real Razorpay test-mode order.

Requires RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET as environment variables.
Never hardcode these, never commit them, never paste them into a chat.

Setup (once, in your terminal — not in this file):
  export RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
  export RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

Run:
  python3 day2/create_test_order.py
"""

import json
import os
import sys

import requests

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")


def _check_env() -> None:
    if not KEY_ID or not KEY_SECRET:
        sys.exit(
            "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET first "
            "(Dashboard -> Test Mode -> Settings -> API Keys)."
        )
    if not KEY_ID.startswith("rzp_test_"):
        # Refuse to run against anything that isn't obviously a test key.
        # This is the same "fail safe, not open" instinct as evaluate_policy()
        # in agent/agent_tools.py — a dev script for a money-adjacent project
        # should have the same reflex the project itself does.
        sys.exit(
            f"RAZORPAY_KEY_ID '{KEY_ID}' does not start with rzp_test_ — "
            "refusing to run against what looks like a live key."
        )


def create_order(amount_rupees: float, receipt: str) -> dict:
    resp = requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(KEY_ID, KEY_SECRET),
        json={
            "amount": int(round(amount_rupees * 100)),  # paise — matches schema.sql's `amount` column
            "currency": "INR",
            "receipt": receipt,
            "notes": {"source": "risk-manager-day2-exercise"},
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    _check_env()
    order = create_order(amount_rupees=499.00, receipt="day2-test-1")
    print(json.dumps(order, indent=2))
    print()
    print(f"Order created: {order['id']}  status={order['status']}  amount={order['amount']} paise")
    print("Next: open day2/checkout.html, paste this order id + your key id in, and complete a test payment.")
