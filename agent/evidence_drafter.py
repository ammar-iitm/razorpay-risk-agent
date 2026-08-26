"""
agent/evidence_drafter.py — real Claude-drafted dispute evidence (Day 8),
replacing the deterministic template that used to live inside
tool_draft_dispute_evidence.

Why this shells out to the `claude` CLI in print mode instead of using
either the plain `anthropic` Python SDK or `claude_agent_sdk`'s
ClaudeSDKClient (already used in agent_tools.py's run_agent()):

- The plain `anthropic` SDK needs a standalone ANTHROPIC_API_KEY — separate
  billing from a Claude subscription. This project's whole Agent SDK setup
  (Day 6, see README's quick start) was deliberately built around the
  user's EXISTING Claude subscription via the authenticated `claude` CLI,
  specifically to avoid that. Using the raw API SDK here would quietly
  reintroduce the cost this project went out of its way to avoid.
- `claude_agent_sdk`'s ClaudeSDKClient is built for a multi-turn, tool-
  calling AGENT loop — exactly what run_agent() already does for deciding
  WHICH action to take. Drafting a letter is a single-turn TEXT GENERATION
  task, not a tool-calling one; wiring the full agent loop machinery in for
  that would be real complexity with nothing to show for it.
- The `claude` CLI's print mode (`claude -p "<prompt>"`) is a synchronous,
  authenticated-via-the-same-subscription, single-turn call — exactly the
  right weight for this job, and it keeps tool_draft_dispute_evidence a
  plain synchronous function like every other tool_* function in
  agent_tools.py (consistent with how tool_hold_payment/tool_release_payment
  also do blocking synchronous I/O via razorpay_client, Day 7).

Deliberately honest about uncertainty: the prompt instructs Claude NOT to
invent supporting facts (delivery confirmations, IP logs, customer
communications) that aren't in the real payment/dispute data — a
convincing-sounding fabricated evidence letter would be a worse demo than
an honest, thinner one that says plainly what data does and doesn't exist.
A human reviews every draft before anything is ever submitted regardless
(policy_config's 'submit_evidence_gate' is approval_required) — this module
only ever produces a DRAFT.

Soft-optional, same pattern as agent/razorpay_client.py: if the `claude`
CLI isn't on PATH, times out, or returns something that doesn't parse as
the expected JSON shape, this returns None and the caller falls back to a
clearly-labeled deterministic template — never a crash, and never a silent
claim that live drafting happened when it didn't.
"""

import json
import re
import shutil
import subprocess
from typing import Optional

CLI_TIMEOUT_SECONDS = 60


def claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def build_prompt(payment: dict, dispute: dict, risk: Optional[dict]) -> str:
    """Pure function — builds the drafting prompt from real DB context.
    Testable with zero network/subprocess calls, same 'pure core' split as
    day5/rule_engine.py and day4/feature_engineering.py."""
    risk_line = "No fraud risk score on file for this payment."
    if risk and risk.get("score") is not None:
        codes = ", ".join(risk.get("reason_codes") or []) or "none"
        risk_line = f"Fraud risk score at time of payment: {risk['score']:.2f} (reason codes: {codes})."

    return f"""You are drafting a chargeback dispute evidence package for a Razorpay merchant. A human reviews every draft before anything is submitted — nothing you write here is sent to Razorpay automatically.

Use ONLY the facts given below. Do NOT invent supporting details (delivery confirmations, customer communications, IP addresses, tracking numbers, or anything else) that aren't listed here. If the available facts are thin, say so plainly in the letter and note what additional evidence the merchant should gather — an honest, thinner letter is more useful to a human reviewer than a fabricated strong one.

Payment facts:
- payment_id: {payment.get('payment_id')}
- amount: {payment.get('amount')} paise ({payment.get('currency', 'INR')})
- method: {payment.get('method')}
- status: {payment.get('status')}
- captured: {bool(payment.get('captured'))}
- email on file: {payment.get('email')}
- contact on file: {payment.get('contact')}
- {risk_line}

Dispute facts:
- dispute_id: {dispute.get('dispute_id')}
- reason_code: {dispute.get('reason_code')}
- disputed amount: {dispute.get('amount')} paise
- respond_by (unix ts): {dispute.get('respond_by')}

Respond with ONLY a single JSON object — no markdown code fences, no text before or after — in exactly this shape:
{{"summary": "<one sentence>", "explanation_letter": "<2-4 paragraph formal letter a merchant could send as-is or edit>", "confidence": <float 0.0-1.0, your own honest estimate of how likely this evidence is to win the dispute given how much real supporting data you actually have — a thin evidence base should get a LOW number, not an optimistic one>}}"""


def _extract_json(text: str) -> Optional[dict]:
    """Claude was told to return raw JSON, but strip code fences defensively
    in case it wraps the response anyway — models don't always follow
    formatting instructions perfectly, and failing to parse is a soft-fail,
    not something worth crashing over."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def draft_with_claude(prompt: str, timeout: int = CLI_TIMEOUT_SECONDS) -> Optional[dict]:
    """Calls the authenticated `claude` CLI in print mode. Returns a dict
    with 'summary'/'explanation_letter'/'confidence' on success, or None on
    ANY failure (CLI missing, timeout, non-zero exit, unparseable response,
    missing/malformed fields) — the caller is responsible for falling back
    to the deterministic template and saying so honestly, never silently."""
    if not claude_cli_available():
        return None
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None

    parsed = _extract_json(result.stdout)
    if not parsed:
        return None
    summary = parsed.get("summary")
    letter = parsed.get("explanation_letter")
    confidence = parsed.get("confidence")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(letter, str) or not letter.strip():
        return None
    if not isinstance(confidence, (int, float)):
        confidence = 0.5  # Claude gave usable text but skipped the number — don't discard a real draft over that.
    confidence = max(0.0, min(1.0, float(confidence)))

    return {"summary": summary.strip(), "explanation_letter": letter.strip(), "confidence": confidence}
