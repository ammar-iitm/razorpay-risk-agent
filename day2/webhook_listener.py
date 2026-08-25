"""
day2/webhook_listener.py — minimal local receiver for Razorpay webhooks.

Verifies the X-Razorpay-Signature header (HMAC-SHA256 against your webhook
secret) BEFORE trusting anything in the payload. Same "verify before you
act" instinct as the rest of this project — just applied to an inbound
webhook instead of an outbound agent tool call. An unverified webhook is a
forged webhook until proven otherwise.

Setup:
  pip install flask   (already installed in most environments — check first)
  export RAZORPAY_WEBHOOK_SECRET=whatever_you_set_in_the_dashboard
  python3 day2/webhook_listener.py

In another terminal:
  ngrok http 5000
  # take the https://xxxx.ngrok-free.app URL it prints, add /webhook to it,
  # and register that full URL in Dashboard -> Settings -> Webhooks.
  # Subscribe to: payment.captured, payment.failed, and the payment.dispute.* events.
"""

import json
import os

from flask import Flask, request, jsonify

from webhook_verify import verify_signature

app = Flask(__name__)
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = request.get_data()

    if not verify_signature(body, signature, WEBHOOK_SECRET):
        print("!!! SIGNATURE MISMATCH — rejecting, not processing payload !!!")
        return jsonify({"status": "signature invalid"}), 400

    payload = json.loads(body)
    event = payload.get("event")
    print(f"\n=== Verified webhook: {event} ===")
    print(json.dumps(payload, indent=2))
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    if not WEBHOOK_SECRET:
        print("WARNING: RAZORPAY_WEBHOOK_SECRET not set — every webhook will be rejected as unverified.")
    app.run(port=5000)
