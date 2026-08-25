"""
day2/webhook_verify.py — the pure signature-verification logic, with zero
dependencies beyond the standard library.

Split out of webhook_listener.py on purpose: verifying a webhook signature
is security-critical logic that should be testable (and tested) without
needing Flask, a running server, or a network connection at all. This is
the same "keep the core logic testable in isolation" instinct as
agent_tools.py's tool_* functions being separable from the eventual Claude
Agent SDK wiring.
"""

import hashlib
import hmac


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Signature is computed over the RAW request body, not parsed-then-
    reserialized JSON — parsing and reserializing can reorder keys or
    change whitespace and silently break verification. Always pass the
    exact bytes as received."""
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")
