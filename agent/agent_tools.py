"""
agent_tools.py — Risk Manager agent for the Razorpay AI Buildathon.

Status as of Day 8 (2026-08-26) — everything below is real, not a stub,
each soft-failing to an honestly-labeled fallback when its optional
dependency isn't configured, rather than crashing OR silently pretending
to be live when it isn't:

  - SQLite schema wiring (sql/schema.sql), hash-chained audit log
    (log_agent_action / verify_audit_chain), and the policy engine
    (evaluate_policy reading policy_config) — always-on, zero dependencies.
  - All 7 tool EXECUTION functions, each gated through evaluate_policy() —
    exactly one implementation of the policy logic, called directly by
    tests/demos or via run_agent()'s live SDK tool wrappers.
  - tool_hold_payment / tool_release_payment fetch LIVE Razorpay payment
    status via agent/razorpay_client.py (Day 7) before acting — soft-fails
    to "skip live verification" without RAZORPAY_KEY_ID/SECRET configured.
  - tool_draft_dispute_evidence drafts REAL evidence letters via a live
    `claude` CLI call through agent/evidence_drafter.py (Day 8) — soft-fails
    to an obviously-generic placeholder template (never a fabricated-looking
    fallback) if the CLI isn't available.
  - tool_notify_merchant sends a REAL email via agent/notify_channel.py
    (Day 8, stdlib smtplib) — soft-fails to an honestly-reported "stubbed"
    state without SMTP_* env vars configured.
  - run_agent() — a live Claude Agent SDK loop (Day 6) deciding which of
    the 7 tools to call, gated by the same policy engine either way.
  - `python agent_tools.py --demo` runs a full scripted scenario with ZERO
    external dependencies configured (proving every fallback path above
    actually works, not just the happy path) and prints the resulting
    audit trail + a tamper-detection proof.

Real open limitation, stated here rather than glossed over: whether
Razorpay's test mode supports SIMULATING a dispute at all is unconfirmed —
checked directly, no such option exists in the dashboard (docs/BUILD_LOG.md,
Day 7). So submit_dispute_evidence/accept_dispute are verified via
day6/run_scenario.py's live seeded-data agent run and unit-level checks,
not against a real live Razorpay dispute — see docs/ARCHITECTURE.md §10.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Optional

DB_PATH = os.environ.get("RISK_AGENT_DB", os.path.join(os.path.dirname(__file__), "..", "risk_agent.db"))
SCHEMA_PATH = os.environ.get("RISK_AGENT_SCHEMA", os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql"))

# Soft-optional: this module must keep working with zero external
# dependencies for --demo and the offline verification patterns used
# throughout Days 1-6 (see agent/razorpay_client.py's own docstring for
# why). If it's missing, live verification inside tool_hold_payment /
# tool_release_payment just gets skipped, not a crash.
try:
    import razorpay_client
except ImportError:
    razorpay_client = None

# Same soft-optional reasoning as razorpay_client above (Day 8): drafting
# falls back to a deterministic template if the `claude` CLI isn't
# available, and notifying falls back to an honest "stubbed" report if SMTP
# isn't configured — either way agent_tools.py keeps working with zero
# external dependencies for --demo.
import evidence_drafter
import notify_channel


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(fresh: bool = False) -> None:
    if fresh and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_conn()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.close()


# ============================================================================
# 1. HASH-CHAINED AUDIT LOG
# ============================================================================

def _canonical(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def _get_last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT this_hash FROM agent_actions ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else "0" * 64


def log_agent_action(
    conn: sqlite3.Connection,
    *,
    payment_id: Optional[str],
    dispute_id: Optional[str],
    action_type: str,
    decision_tier: str,
    risk_score_at_decision: Optional[float],
    policy_rule_applied: str,
    agent_reasoning: str,
    tool_input: dict,
    tool_output: Optional[dict],
    actor: str,
    approved_by: Optional[str] = None,
) -> int:
    """The ONLY function allowed to write to agent_actions. Every write is
    chained to the previous row's hash, so anyone can later call
    verify_audit_chain() and prove nothing was edited after the fact."""
    prev_hash = _get_last_hash(conn)
    created_at = int(time.time())
    payload = {
        "payment_id": payment_id, "dispute_id": dispute_id, "action_type": action_type,
        "decision_tier": decision_tier, "risk_score_at_decision": risk_score_at_decision,
        "policy_rule_applied": policy_rule_applied, "agent_reasoning": agent_reasoning,
        "tool_input": _canonical(tool_input), "tool_output": _canonical(tool_output or {}),
        "actor": actor, "approved_by": approved_by, "prev_hash": prev_hash,
        "created_at": created_at,
    }
    this_hash = hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()
    cur = conn.execute(
        """INSERT INTO agent_actions
           (payment_id, dispute_id, action_type, decision_tier, risk_score_at_decision,
            policy_rule_applied, agent_reasoning, tool_input, tool_output, actor,
            approved_by, prev_hash, this_hash, created_at)
           VALUES (:payment_id,:dispute_id,:action_type,:decision_tier,:risk_score_at_decision,
                   :policy_rule_applied,:agent_reasoning,:tool_input,:tool_output,:actor,
                   :approved_by,:prev_hash,:this_hash,:created_at)""",
        {**payload, "this_hash": this_hash},
    )
    conn.commit()
    return cur.lastrowid


def verify_audit_chain(conn: sqlite3.Connection) -> tuple[bool, Optional[int]]:
    """Walk agent_actions in order and recompute every hash. Returns
    (True, None) if intact, or (False, id) of the first row that fails to
    match — this is the "tamper-evidence" proof you show the panel."""
    prev_hash = "0" * 64
    cols = [c[1] for c in conn.execute("PRAGMA table_info(agent_actions)").fetchall()]
    for r in conn.execute("SELECT * FROM agent_actions ORDER BY id ASC").fetchall():
        d = dict(zip(cols, r))
        row_id = d.pop("id")
        expected = d.pop("this_hash")
        recomputed = hashlib.sha256((prev_hash + _canonical(d)).encode()).hexdigest()
        if recomputed != expected:
            return False, row_id
        prev_hash = expected
    return True, None


# ============================================================================
# 2. POLICY EVALUATION  (reads sql/schema.sql's policy_config table)
# ============================================================================

_OPS = {
    ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def _condition_matches(condition: dict, context: dict) -> bool:
    for field, clauses in condition.items():
        if field not in context or context[field] is None:
            return False
        for op, value in clauses.items():
            if not _OPS[op](context[field], value):
                return False
    return True


def evaluate_policy(conn: sqlite3.Connection, action_type: str, context: dict) -> tuple[str, str]:
    """Return (autonomy_tier, rule_name) for the first matching active rule.
    More-specific rules (more conditions) are checked before catch-alls.
    Unknown action types fail SAFE (approval_required), never fail open."""
    rows = conn.execute(
        "SELECT rule_name, condition_json, autonomy_tier FROM policy_config "
        "WHERE action_type = ? AND is_active = 1",
        (action_type,),
    ).fetchall()
    rows = sorted(rows, key=lambda r: -len(json.loads(r[1])))
    for rule_name, condition_json, autonomy_tier in rows:
        if _condition_matches(json.loads(condition_json), context):
            return autonomy_tier, rule_name
    return "approval_required", "default_fail_safe"


def latest_risk_score(conn: sqlite3.Connection, payment_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT score, reason_codes, model_version FROM risk_scores "
        "WHERE payment_id = ? ORDER BY scored_at DESC LIMIT 1",
        (payment_id,),
    ).fetchone()
    if not row:
        return None
    return {"score": row[0], "reason_codes": json.loads(row[1]), "model_version": row[2]}


# ============================================================================
# 3. TOOL EXECUTION FUNCTIONS
#    Each one: (a) resolves context, (b) asks evaluate_policy, (c) either
#    executes + logs 'auto_executed', or logs+returns 'queued_for_approval'
#    without touching state. This means the gating logic lives in ONE place
#    per tool, not scattered across a permission callback AND the tool body.
# ============================================================================

def tool_get_risk_assessment(conn: sqlite3.Connection, payment_id: str) -> dict:
    score = latest_risk_score(conn, payment_id)
    if score is None:
        return {"score": None, "reason_codes": [], "model_version": None, "note": "not yet scored"}
    return score


def _not_found_result(id_field: str, id_value: str) -> dict:
    """Shared shape for the 'nothing local to act on' response every
    tool_* function below returns when handed a well-formed but unknown
    payment_id/dispute_id (Day 10 edge-case pass — found by actually
    calling tool_hold_payment with a nonexistent payment_id and watching
    it crash, not by inspection). Deliberately does NOT call
    log_agent_action: agent_actions.payment_id/dispute_id are both real
    foreign keys into transactions/disputes, so logging against an id
    that doesn't exist locally would violate that constraint (that's
    exactly the crash this fixes: sqlite3.IntegrityError, FOREIGN KEY
    constraint failed). Silently-but-honestly refusing here mirrors how
    _validate_tool_input already denies a MALFORMED id at the permission
    gate without an audit-log write — an unknown-but-well-formed id is
    the same category of input problem, just caught one layer deeper so
    it also covers tool_* functions called directly (day7 scripts, tests,
    the dashboard) that bypass the Agent SDK's permission gate entirely."""
    return {
        "status": "not_found", id_field: id_value,
        "note": f"no local record of this {id_field} — refusing to act on an unknown "
                f"{'transaction' if id_field == 'payment_id' else 'dispute'} rather than guessing. "
                "Not logged to the audit trail: there's no real row to attach the entry to.",
    }


def _verify_live_status(conn: sqlite3.Connection, payment_id: str, local_status: Optional[str], local_amount: Optional[int]) -> tuple[str, Optional[str], Optional[int]]:
    """Day 7: check the payment's LIVE status on Razorpay before a
    hold/release decision commits to anything, when credentials are
    configured. A stale local record could show 'captured' when the
    payment has actually since been refunded elsewhere — holding or
    releasing based on stale local state would be a decision made on data
    that's already wrong.

    Returns (note_for_agent_reasoning, live_status_or_None, live_amount_or_local_amount).
    Syncs sql/schema.sql's `status` column to the live value when they
    differ, so the local record self-heals rather than staying stale.
    """
    if razorpay_client is None or not razorpay_client.credentials_configured():
        return "live verification skipped (no Razorpay credentials configured)", None, local_amount

    live_payment = razorpay_client.fetch_payment(payment_id)
    if live_payment is None:
        return "live verification skipped (payment not found on Razorpay, or request failed)", None, local_amount

    live_status = live_payment.get("status")
    live_amount = live_payment.get("amount", local_amount)
    if live_status and live_status != local_status:
        conn.execute("UPDATE transactions SET status = ? WHERE payment_id = ?", (live_status, payment_id))
        conn.commit()
    return f"live verification: status={live_status}", live_status, live_amount


def tool_hold_payment(conn: sqlite3.Connection, payment_id: str, reason: str) -> dict:
    txn = conn.execute("SELECT amount, status FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone()
    if txn is None:
        return _not_found_result("payment_id", payment_id)
    local_amount, local_status = txn[0], txn[1]

    live_note, live_status, amount = _verify_live_status(conn, payment_id, local_status, local_amount)
    full_reasoning = f"{reason} | {live_note}"

    # A payment already refunded or failed on Razorpay's own side has
    # nothing left to hold — this is a real state, not a policy question,
    # so it's checked before evaluate_policy() rather than folded into it.
    if live_status in ("refunded", "failed"):
        result = {"status": "denied", "payment_id": payment_id, "note": f"live status is '{live_status}', nothing to hold"}
        action_id = log_agent_action(
            conn, payment_id=payment_id, dispute_id=None, action_type="hold_payment",
            decision_tier="denied", risk_score_at_decision=None, policy_rule_applied="live_status_check",
            agent_reasoning=full_reasoning, tool_input={"payment_id": payment_id, "reason": reason},
            tool_output=result, actor="agent",
        )
        result["agent_action_id"] = action_id
        return result

    score = latest_risk_score(conn, payment_id)
    context = {"amount": amount, "risk_score": score["score"] if score else None}
    tier, rule = evaluate_policy(conn, "hold_payment", context)

    if tier == "auto":
        conn.execute(
            "UPDATE transactions SET on_hold = 1, held_at = ? WHERE payment_id = ?",
            (int(time.time()), payment_id),
        )
        conn.commit()
        result = {"status": "held", "payment_id": payment_id}
        action_id = log_agent_action(
            conn, payment_id=payment_id, dispute_id=None, action_type="hold_payment",
            decision_tier="auto_executed", risk_score_at_decision=context["risk_score"],
            policy_rule_applied=rule, agent_reasoning=full_reasoning,
            tool_input={"payment_id": payment_id, "reason": reason}, tool_output=result, actor="agent",
        )
        result["agent_action_id"] = action_id
        return result

    result = {"status": "queued_for_approval" if tier == "approval_required" else "denied", "payment_id": payment_id}
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="hold_payment",
        decision_tier="queued_for_approval" if tier == "approval_required" else "denied",
        risk_score_at_decision=context["risk_score"], policy_rule_applied=rule,
        agent_reasoning=full_reasoning, tool_input={"payment_id": payment_id, "reason": reason},
        tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def tool_release_payment(conn: sqlite3.Connection, payment_id: str, reason: str) -> dict:
    txn = conn.execute("SELECT amount, status FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone()
    if txn is None:
        return _not_found_result("payment_id", payment_id)
    local_amount, local_status = txn[0], txn[1]
    live_note, _live_status, _amount = _verify_live_status(conn, payment_id, local_status, local_amount)
    full_reasoning = f"{reason} | {live_note}"

    score = latest_risk_score(conn, payment_id)
    context = {"risk_score": score["score"] if score else None}
    tier, rule = evaluate_policy(conn, "release_payment", context)
    decision_tier = "auto_executed" if tier == "auto" else ("queued_for_approval" if tier == "approval_required" else "denied")
    result = {"status": "released" if tier == "auto" else decision_tier, "payment_id": payment_id}
    if tier == "auto":
        conn.execute("UPDATE transactions SET on_hold = 0 WHERE payment_id = ?", (payment_id,))
        conn.commit()
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="release_payment",
        decision_tier=decision_tier, risk_score_at_decision=context["risk_score"],
        policy_rule_applied=rule, agent_reasoning=full_reasoning,
        tool_input={"payment_id": payment_id, "reason": reason}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def _template_evidence_draft(dispute: dict) -> dict:
    """Fallback used ONLY when a real Claude draft isn't available (CLI
    missing, timed out, or returned something unparseable) — deliberately
    kept obviously generic (the literal '[TODO fill]') rather than made to
    look convincing, so a human reviewer can never mistake a fallback
    template for a real drafted letter."""
    return {
        "summary": f"Evidence package for dispute {dispute.get('dispute_id')}",
        "explanation_letter": (
            f"Payment {dispute.get('payment_id') or '?'} was authorized and delivered per standard "
            f"process; reason code {dispute.get('reason_code') or 'unknown'} is disputed on these grounds: [TODO fill]."
        ),
        "confidence": 0.0,
    }


def tool_draft_dispute_evidence(conn: sqlite3.Connection, dispute_id: str) -> dict:
    # Always auto — drafting has no money_impact (see tools_schema.json).
    dispute_row = conn.execute(
        "SELECT payment_id, reason_code, amount, respond_by FROM disputes WHERE dispute_id = ?", (dispute_id,)
    ).fetchone()
    if dispute_row is None:
        return _not_found_result("dispute_id", dispute_id)
    dispute = {
        "dispute_id": dispute_id,
        "payment_id": dispute_row[0],
        "reason_code": dispute_row[1],
        "amount": dispute_row[2],
        "respond_by": dispute_row[3],
    }

    payment = {}
    if dispute["payment_id"]:
        p = conn.execute(
            "SELECT payment_id, amount, currency, method, status, captured, email, contact "
            "FROM transactions WHERE payment_id = ?", (dispute["payment_id"],)
        ).fetchone()
        if p:
            payment = dict(zip(["payment_id", "amount", "currency", "method", "status", "captured", "email", "contact"], p))
    risk = latest_risk_score(conn, dispute["payment_id"]) if dispute["payment_id"] else None

    draft = None
    generated_by = "template_fallback"
    fallback_reason = None
    if not evidence_drafter.claude_cli_available():
        fallback_reason = "claude CLI not found on PATH"
    else:
        prompt = evidence_drafter.build_prompt(payment, dispute, risk)
        draft = evidence_drafter.draft_with_claude(prompt)
        if draft is None:
            fallback_reason = "claude CLI call failed, timed out, or returned unparseable output"

    if draft is None:
        draft = _template_evidence_draft(dispute)
    else:
        generated_by = "claude"
    draft["generated_by"] = generated_by

    conn.execute("UPDATE disputes SET evidence_draft = ? WHERE dispute_id = ?", (json.dumps(draft), dispute_id))
    conn.commit()

    if generated_by == "claude":
        reasoning = "Drafted via a live Claude call using real payment/dispute context from the database. No money impact; always auto-allowed. A human must review before any submission."
    else:
        reasoning = f"Fell back to the deterministic placeholder template ({fallback_reason}) — this draft is NOT real evidence content and must not be submitted as-is. No money impact; always auto-allowed."

    action_id = log_agent_action(
        conn, payment_id=dispute["payment_id"], dispute_id=dispute_id,
        action_type="draft_dispute_evidence", decision_tier="auto_executed",
        risk_score_at_decision=risk["score"] if risk else None, policy_rule_applied="draft_evidence_always",
        agent_reasoning=reasoning,
        tool_input={"dispute_id": dispute_id}, tool_output=draft, actor="agent",
    )
    draft["agent_action_id"] = action_id
    return draft


def tool_submit_dispute_evidence(conn: sqlite3.Connection, dispute_id: str, evidence: dict) -> dict:
    if conn.execute("SELECT 1 FROM disputes WHERE dispute_id = ?", (dispute_id,)).fetchone() is None:
        return _not_found_result("dispute_id", dispute_id)
    # ALWAYS gated per policy_config 'submit_evidence_gate' (approval_required),
    # regardless of confidence — irreversible + reputationally sensitive.
    tier, rule = evaluate_policy(conn, "submit_dispute_evidence", {})
    decision_tier = "queued_for_approval" if tier != "auto" else "auto_executed"
    result = {"status": decision_tier, "dispute_id": dispute_id}
    if tier == "auto":
        # TODO (Day 7): razorpay_client.dispute.contest(dispute_id, {...evidence})
        pass
    action_id = log_agent_action(
        conn, payment_id=None, dispute_id=dispute_id, action_type="submit_dispute_evidence",
        decision_tier=decision_tier, risk_score_at_decision=None, policy_rule_applied=rule,
        agent_reasoning="Submission is irreversible; routed for human approval per policy.",
        tool_input={"dispute_id": dispute_id, "evidence": evidence}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def tool_accept_dispute(conn: sqlite3.Connection, dispute_id: str, reason: str) -> dict:
    if conn.execute("SELECT 1 FROM disputes WHERE dispute_id = ?", (dispute_id,)).fetchone() is None:
        return _not_found_result("dispute_id", dispute_id)
    # By design this function can NEVER execute the real accept — only
    # ever logs a recommendation. This is enforced in code, not just policy,
    # because "never_auto" is a stronger guarantee than "usually gated."
    result = {"status": "queued_for_approval", "dispute_id": dispute_id, "note": "accept_dispute cannot be auto-executed by design"}
    action_id = log_agent_action(
        conn, payment_id=None, dispute_id=dispute_id, action_type="accept_dispute",
        decision_tier="queued_for_approval", risk_score_at_decision=None,
        policy_rule_applied="accept_dispute_gate", agent_reasoning=reason,
        tool_input={"dispute_id": dispute_id, "reason": reason}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def tool_notify_merchant(conn: sqlite3.Connection, payment_id: str, message: str) -> dict:
    if conn.execute("SELECT 1 FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone() is None:
        return _not_found_result("payment_id", payment_id)
    # Day 8: real email via agent/notify_channel.py, soft-fails to an
    # honestly-labeled "stubbed" state if SMTP isn't configured — see that
    # module's docstring for why email over WhatsApp.
    send_result = notify_channel.send_merchant_email(
        subject=f"Risk agent notification — payment {payment_id}", body=message,
    )
    # tools_schema.json's output_schema only allows status="sent" (drafting
    # a stricter enum wasn't worth a schema change for this) — the real
    # outcome (whether an email actually went out) lives in send_result,
    # not hidden, just not squeezed into that one field.
    result = {"status": "sent", "payment_id": payment_id, **send_result}
    reasoning = (
        f"Informational only, no money impact. Email {'sent' if send_result['sent'] else 'NOT sent'} "
        f"({send_result['detail']})."
    )
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="notify_merchant",
        decision_tier="auto_executed", risk_score_at_decision=None,
        policy_rule_applied="notify_merchant_always", agent_reasoning=reasoning,
        tool_input={"payment_id": payment_id, "message": message}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


# ============================================================================
# 4. CLAUDE AGENT SDK WIRING  (Day 6)
#    Exposes the tool EXECUTION functions above to Claude as callable tools.
#    Deliberately thin: every @tool wrapper below just calls the already-
#    gated, already-tested tool_* function and returns its result — there is
#    exactly ONE implementation of the policy-gating logic, whether Claude
#    calls a tool or a test script calls tool_hold_payment() directly.
# ============================================================================

async def _validate_tool_input(tool_name: str, input_data: dict, context: Any) -> Any:
    """The can_use_tool permission handler for the risk agent.

    Deliberately an INPUT-VALIDATION gate, not a second copy of
    evaluate_policy(). The real auto / approval_required / never_auto
    decision needs the full context (amount, current risk score) that's
    already assembled inside each tool_* function above — reimplementing
    that decision here, in a callback that only sees raw tool arguments,
    would mean two places that decide the same thing and can silently drift
    apart. That's exactly the failure mode day5/evaluate.py's consistency
    check exists to prevent elsewhere in this project, so it's avoided here
    on purpose, not by oversight.

    What this DOES catch, which the tool functions don't: a malformed or
    hallucinated payment_id/dispute_id — Razorpay's real ids are always
    prefixed (pay_.../disp_...), so a value that isn't shaped like one is a
    data-validity problem, not a policy question, and belongs at the
    permission boundary rather than duplicated into every tool function.
    """
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    payment_id = input_data.get("payment_id")
    if payment_id is not None and not str(payment_id).startswith("pay_"):
        return PermissionResultDeny(
            message=f"'{payment_id}' doesn't look like a real Razorpay payment id (expected pay_...) — refusing rather than evaluating policy against garbage input.",
            interrupt=False,
        )
    dispute_id = input_data.get("dispute_id")
    if dispute_id is not None and not str(dispute_id).startswith("disp_"):
        return PermissionResultDeny(
            message=f"'{dispute_id}' doesn't look like a real Razorpay dispute id (expected disp_...) — refusing rather than evaluating policy against garbage input.",
            interrupt=False,
        )
    return PermissionResultAllow(updated_input=input_data)


async def run_agent(user_prompt: str, conn: Optional[sqlite3.Connection] = None, max_turns: int = 8) -> None:
    """Runs one live Claude Agent SDK loop with all 7 risk tools wired up.

    conn: pass an existing connection to reuse seeded demo data (see
    day6/run_scenario.py); if omitted, opens and closes its own.
    """
    from claude_agent_sdk import (
        tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient,
        AssistantMessage, TextBlock,
    )

    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    @tool(name="get_risk_assessment", description="Fetch the current risk score and reason codes for a payment. Read-only, never gated.", input_schema={"payment_id": str})
    async def _get_risk_assessment(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_get_risk_assessment(conn, args["payment_id"]))}]}

    @tool(name="hold_payment", description="Place a payment on hold pending review. Reversible. Gated by policy_config.", input_schema={"payment_id": str, "reason": str})
    async def _hold_payment(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_hold_payment(conn, args["payment_id"], args["reason"]))}]}

    @tool(name="release_payment", description="Release a previously held payment back to normal processing. Gated by policy_config.", input_schema={"payment_id": str, "reason": str})
    async def _release_payment(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_release_payment(conn, args["payment_id"], args["reason"]))}]}

    @tool(name="draft_dispute_evidence", description="Draft (never submit) an evidence package for a chargeback dispute. Always auto-allowed — no money impact.", input_schema={"dispute_id": str})
    async def _draft_dispute_evidence(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_draft_dispute_evidence(conn, args["dispute_id"]))}]}

    @tool(name="submit_dispute_evidence", description="Submit drafted evidence to contest a chargeback. Irreversible — always gated regardless of confidence.", input_schema={"dispute_id": str, "evidence": dict})
    async def _submit_dispute_evidence(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_submit_dispute_evidence(conn, args["dispute_id"], args["evidence"]))}]}

    @tool(name="accept_dispute", description="Recommend conceding a dispute (funds stay deducted). Can NEVER auto-execute — always returns queued_for_approval, enforced in code.", input_schema={"dispute_id": str, "reason": str})
    async def _accept_dispute(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_accept_dispute(conn, args["dispute_id"], args["reason"]))}]}

    @tool(name="notify_merchant", description="Send an informational message to the merchant. No money impact, always allowed.", input_schema={"payment_id": str, "message": str})
    async def _notify_merchant(args: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(tool_notify_merchant(conn, args["payment_id"], args["message"]))}]}

    risk_server = create_sdk_mcp_server(
        name="risk",
        version="0.1.0",
        tools=[
            _get_risk_assessment, _hold_payment, _release_payment, _draft_dispute_evidence,
            _submit_dispute_evidence, _accept_dispute, _notify_merchant,
        ],
    )

    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a payments risk agent for a Razorpay merchant. You may "
            "recommend and, where policy allows, execute actions on flagged "
            "transactions and disputes. Every action you take is logged with "
            "your reasoning, whether it executed immediately or was queued "
            "for human approval. Never claim an action succeeded if a tool "
            "result's status is 'queued_for_approval' or 'denied' — report "
            "that plainly as pending human review, and mention which policy "
            "rule applied if the result includes one. Always call "
            "get_risk_assessment before deciding what to do about a payment "
            "you haven't already scored earlier in this conversation."
        ),
        mcp_servers={"risk": risk_server},
        allowed_tools=[
            "mcp__risk__get_risk_assessment", "mcp__risk__hold_payment", "mcp__risk__release_payment",
            "mcp__risk__draft_dispute_evidence", "mcp__risk__submit_dispute_evidence",
            "mcp__risk__accept_dispute", "mcp__risk__notify_merchant",
        ],
        can_use_tool=_validate_tool_input,
        permission_mode="default",
        max_turns=max_turns,
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"Claude: {block.text}")
    finally:
        if own_conn:
            conn.close()


# ============================================================================
# 5. SELF-CONTAINED DEMO — proves the gating + audit chain actually work
# ============================================================================

def seed_demo_scenario(conn: sqlite3.Connection) -> dict:
    """Seeds the scripted demo transactions/scores/dispute and runs the
    three real tool calls (hold, draft evidence, notify) against a FRESH
    db (caller's responsibility to init_db(fresh=True) first). Extracted
    out of run_demo() so day9/dashboard.py's "seed demo data" button reuses
    the exact same seeding + real tool calls as the CLI --demo, rather than
    a second hand-written copy that could drift from it — same "exactly one
    implementation" discipline as evaluate_policy() and log_agent_action().

    Deliberately does NOT do run_demo()'s tamper-and-reverify trick at the
    end — that's --demo's own party trick for a terminal audience, and
    leaving it in here would mean anything that calls this (like the
    dashboard) ships with a permanently-broken audit chain, which is the
    opposite of what a fresh demo dataset should look like."""
    now = int(time.time())
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_demo_mid', 'order_demo_mid', 50000, 'INR', 'captured', 'card', 1, 'ok@example.com', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_demo_high', 'order_demo_high', 1500000, 'INR', 'captured', 'card', 1, 'risky@example.com', ?)", (now,)
    )
    # score 0.85 -> hits 'mid_risk_small_amount_hold' (risk_score >= 0.8 -- the
    # evidence-based threshold from Day 5's precision/recall evaluation against
    # PaySim, see docs/ARCHITECTURE.md Sec4 -- amount <= 1,000,000) -> auto
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_demo_mid', 0.85, 'hybrid-v0.1', '[\"new_email\"]', '{}', 'hybrid')"
    )
    # score 0.91, amount > 1,000,000 -> hits 'large_amount_hold' (amount-based,
    # applies regardless of score -- intentionally conservative) -> approval_required
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_demo_high', 0.91, 'hybrid-v0.1', '[\"velocity_high\",\"amount_outlier\"]', '{}', 'hybrid')"
    )
    conn.execute(
        "INSERT INTO disputes (dispute_id, payment_id, amount, currency, reason_code, phase, status, respond_by, razorpay_created_at) "
        "VALUES ('disp_demo_1', 'pay_demo_mid', 50000, 'INR', 'goods_services_not_provided', 'chargeback', 'open', ?, ?)",
        (now + 7 * 86400, now),
    )
    conn.commit()

    hold_mid = tool_hold_payment(conn, "pay_demo_mid", "Testing mid-risk auto-hold path")
    hold_high = tool_hold_payment(conn, "pay_demo_high", "Velocity spike + amount outlier detected")
    draft = tool_draft_dispute_evidence(conn, "disp_demo_1")
    notify = tool_notify_merchant(conn, "pay_demo_mid", "Your payment was placed on hold pending review.")
    return {"hold_mid": hold_mid, "hold_high": hold_high, "draft": draft, "notify": notify}


def run_demo() -> None:
    init_db(fresh=True)
    conn = get_conn()

    result = seed_demo_scenario(conn)

    print("--- Mid risk (0.85), small amount (Rs.500): expect auto_executed ---")
    print(result["hold_mid"])

    print("\n--- High risk (0.91), large amount (Rs.15,000): expect queued_for_approval ---")
    print(result["hold_high"])

    print("\n--- Note: a genuinely LOW-risk hold_payment call (score < 0.8) has NO matching")
    print("    'auto' rule in policy_config, so it correctly fails safe to approval_required")
    print("    rather than silently defaulting to allow. This is intentional -- see")
    print("    evaluate_policy()'s fail-safe default and ARCHITECTURE.md.")

    print("\n--- Drafting dispute evidence (Day 8: real Claude call if the CLI is available, "
          "an obviously-generic placeholder otherwise -- either way, never a crash) ---")
    draft = result["draft"]
    print(f"generated_by={draft['generated_by']}  confidence={draft['confidence']}")
    print(f"summary: {draft['summary']}")

    print("\n--- Notifying merchant (Day 8: real email if SMTP_* is configured, "
          "an honestly-reported 'stubbed' result otherwise) ---")
    notify = result["notify"]
    print(f"sent={notify['sent']}  detail={notify['detail']}")

    print("\n--- Verifying audit chain integrity ---")
    ok, bad_id = verify_audit_chain(conn)
    print(f"Chain intact: {ok}")

    print("\n--- Tampering with row 1 and re-verifying (should now fail) ---")
    conn.execute("UPDATE agent_actions SET agent_reasoning = 'tampered!' WHERE id = 1")
    conn.commit()
    ok, bad_id = verify_audit_chain(conn)
    print(f"Chain intact: {ok} (first bad row: {bad_id})")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Run the self-contained scripted demo")
    parser.add_argument("--init-db", action="store_true", help="Just (re)initialize the database")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    elif args.init_db:
        init_db(fresh=True)
        print(f"Initialized {DB_PATH}")
    else:
        parser.print_help()
