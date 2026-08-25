"""
day2/fetch_payment.py — fetch a payment and show exactly how it maps onto
sql/schema.sql's `transactions` table.

Run this after completing a test payment via day2/checkout.html, using the
payment id it shows you (starts with "pay_").

Run:
  python3 day2/fetch_payment.py pay_XXXXXXXXXXXXXX
"""

import json
import os
import sys

import requests

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")


def map_to_transactions_row(p: dict) -> dict:
    """This mapping MUST match sql/schema.sql's `transactions` columns
    exactly — if a field below is missing/None where you expected data,
    that's the thing to go fix (in schema.sql or your ingest code) before
    Day 4, not something to patch around silently later."""
    card = p.get("card") or {}
    return {
        "payment_id": p.get("id"),
        "order_id": p.get("order_id"),
        "amount": p.get("amount"),
        "currency": p.get("currency"),
        "status": p.get("status"),
        "method": p.get("method"),
        "captured": int(bool(p.get("captured"))),
        "email": p.get("email"),
        "contact": p.get("contact"),
        "card_network": card.get("network"),
        "card_last4": card.get("last4"),
        "vpa": p.get("vpa"),
        "bank": p.get("bank"),
        "error_code": p.get("error_code"),
        "error_description": p.get("error_description"),
        "error_reason": p.get("error_reason"),
        "razorpay_created_at": p.get("created_at"),
    }


def fetch_payment(payment_id: str) -> dict:
    resp = requests.get(
        f"https://api.razorpay.com/v1/payments/{payment_id}",
        auth=(KEY_ID, KEY_SECRET),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    if not KEY_ID or not KEY_SECRET:
        sys.exit("Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET first.")
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 day2/fetch_payment.py pay_XXXXXXXXXXXX")

    payment = fetch_payment(sys.argv[1])
    print("--- Raw payment entity (from Razorpay) ---")
    print(json.dumps(payment, indent=2))

    print("\n--- Mapped onto transactions columns (sql/schema.sql) ---")
    print(json.dumps(map_to_transactions_row(payment), indent=2))
