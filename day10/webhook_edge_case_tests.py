"""
day10/webhook_edge_case_tests.py — real HTTP-level fuzzing of
day2/webhook_listener.py's /webhook route via Flask's test client. Every
body below is actually POSTed, correctly signed (except the two deliberate
signature-failure controls), against the real route. A body's SHAPE
(not-a-dict, binary garbage, huge, deeply nested, duplicate keys) is what
this file probes; day10/edge_case_tests.py covers the policy/audit-chain
layer instead.

Run: python3 day10/webhook_edge_case_tests.py
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "day2"))

SECRET = "test_secret_123"


def _client():
    os.environ["RAZORPAY_WEBHOOK_SECRET"] = SECRET
    import webhook_listener
    importlib.reload(webhook_listener)
    webhook_listener.WEBHOOK_SECRET = SECRET
    webhook_listener.app.testing = True
    return webhook_listener.app.test_client()


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


RESULTS = []


def check(name, body: bytes, expect_status: int, sig: str | None = None):
    client = _client()
    signature = _sign(body) if sig is None else sig
    try:
        resp = client.post("/webhook", data=body, headers={"X-Razorpay-Signature": signature})
        if resp.status_code == expect_status:
            RESULTS.append((name, "PASS", None))
        else:
            RESULTS.append((name, "BUG", f"expected {expect_status}, got {resp.status_code}: {resp.get_data(as_text=True)[:150]}"))
    except Exception as e:
        RESULTS.append((name, "BUG", f"{type(e).__name__}: {e}"))


CASES = [
    ("empty body", b"", 400, None),
    ("valid JSON array, not dict", b"[1,2,3]", 400, None),
    ("valid JSON number, not dict", b"42", 400, None),
    ("valid JSON string, not dict", b'"just a string"', 400, None),
    ("valid JSON null", b"null", 400, None),
    ("valid JSON bool true, not dict", b"true", 400, None),
    ("non-UTF8 garbage bytes", b"\xff\xfe\x00\x01not utf8 at all", 400, None),
    ("nested array-of-objects, not dict", b'[{"event":"x"}]', 400, None),
    ("valid dict but no 'event' key", b'{"foo":"bar"}', 200, None),
    ("valid dict, event is null", b'{"event":null}', 200, None),
    ("deeply nested dict (100 levels)", b'{"event":"x","d":' + b'{"n":' * 100 + b'1' + b'}' * 100 + b'}', 200, None),
    ("huge but valid dict (~500KB)", b'{"event":"payment.captured","data":{"x":"' + b"a" * 500000 + b'"}}', 200, None),
    ("duplicate keys in JSON (last wins per spec)", b'{"event":"first","event":"second"}', 200, None),
    ("unicode payload with emoji", '{"event":"payment.captured","note":"\U0001f525 test 测试"}'.encode(), 200, None),
    ("wrong signature entirely", b'{"event":"payment.captured"}', 400, "deadbeef" * 8),
    ("missing signature header (empty string)", b'{"event":"payment.captured"}', 400, ""),
]


if __name__ == "__main__":
    for name, body, expect_status, sig in CASES:
        check(name, body, expect_status, sig)

    # One more case that needs its own client setup: an empty configured
    # secret should reject everything, since verify_signature() treats a
    # falsy secret as "nothing to check against" rather than "anything
    # matches."
    client = _client()
    import webhook_listener
    webhook_listener.WEBHOOK_SECRET = ""
    body = b'{"event":"payment.captured"}'
    try:
        resp = client.post("/webhook", data=body, headers={"X-Razorpay-Signature": _sign(body)})
        if resp.status_code == 400:
            RESULTS.append(("empty WEBHOOK_SECRET configured -> always rejects", "PASS", None))
        else:
            RESULTS.append(("empty WEBHOOK_SECRET configured -> always rejects", "BUG", f"got {resp.status_code}"))
    except Exception as e:
        RESULTS.append(("empty WEBHOOK_SECRET configured -> always rejects", "BUG", f"{type(e).__name__}: {e}"))

    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    n_bug = sum(1 for _, s, _ in RESULTS if s == "BUG")
    for name, status, detail in RESULTS:
        marker = "PASS" if status == "PASS" else "BUG "
        line = f"[{marker}] {name}"
        if detail:
            line += f"  -- {detail}"
        print(line)
    print(f"\n{n_pass}/{len(RESULTS)} passed, {n_bug} bug(s) found.")
    sys.exit(1 if n_bug else 0)
