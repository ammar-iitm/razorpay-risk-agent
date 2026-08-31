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

    # A signature can verify against bytes that still aren't valid JSON --
    # signing only proves the sender knew the secret, not that the body
    # parses. Found this the hard way (Day 10 edge-case pass): an unhandled
    # json.loads() here turns a malformed body into a raw 500 with a
    # traceback dumped to the terminal, and — worse for a real integration
    # — Razorpay's webhook delivery treats a non-2xx as a delivery failure
    # and retries, so a single bad payload would otherwise retry forever
    # rather than failing once and staying failed.
    #
    # Two distinct ways a signed body can fail to become a usable payload,
    # found by actually throwing both at this route (day10/edge_case_tests.py
    # doesn't cover Flask routes, so this was a separate manual pass — see
    # docs/BUILD_LOG.md): (1) json.loads() raises JSONDecodeError on bytes
    # that aren't valid JSON at all; (2) json.loads() ALSO raises
    # UnicodeDecodeError, not JSONDecodeError, when it tries to auto-detect
    # a text encoding (utf-8/16/32) from raw bytes that aren't valid text in
    # any of them — a genuinely different exception type the original
    # except clause didn't catch, so a body of random binary garbage still
    # produced a raw 500.
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"!!! SIGNATURE VALID but body is not valid JSON — rejecting: {e} !!!")
        return jsonify({"status": "invalid JSON body"}), 400

    # A signed body can also be valid JSON that ISN'T a JSON object --
    # a bare array, number, string, or null all parse cleanly but have no
    # .get() method. Razorpay's real webhooks are always a JSON object, so
    # anything else is a malformed payload, not a real event. Found by
    # throwing `[1,2,3]` (and a few other non-dict-but-valid-JSON bodies)
    # at this route: AttributeError: 'list' object has no attribute 'get' ->
    # another raw 500 the signature check alone can't prevent.
    if not isinstance(payload, dict):
        print(f"!!! SIGNATURE VALID, body is valid JSON, but not a JSON object (got {type(payload).__name__}) — rejecting !!!")
        return jsonify({"status": "JSON body must be an object"}), 400

    event = payload.get("event")
    print(f"\n=== Verified webhook: {event} ===")
    print(json.dumps(payload, indent=2))
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    if not WEBHOOK_SECRET:
        print("WARNING: RAZORPAY_WEBHOOK_SECRET not set — every webhook will be rejected as unverified.")
    app.run(port=5000)
