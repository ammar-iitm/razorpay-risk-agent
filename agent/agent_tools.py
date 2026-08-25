"""
agent_tools.py — Risk Manager agent skeleton for the Razorpay AI Buildathon.

What's REAL and runs right now, no API key needed:
  - SQLite schema wiring (sql/schema.sql)
  - Hash-chained audit log (log_agent_action / verify_audit_chain)
  - Policy evaluation engine (evaluate_policy) reading policy_config
  - All 7 tool EXECUTION functions and the gating logic around them
  - `python agent_tools.py --demo` runs a full scripted scenario end to end
    and prints the resulting audit trail + a tamper-detection proof

What's a STUB (clearly marked TODO) because it needs your Razorpay test
keys and the actual Claude Agent SDK agent loop:
  - The Razorpay API calls inside each tool (currently no-ops / mocked returns)
  - `run_agent()` — wires everything into ClaudeSDKClient so Claude itself
    decides which tool to call, in natural language, from a transaction feed

Fill in the TODOs on Day 4 (agent wiring) and Day 6 (real Razorpay calls) of
the build tracker. Everything else here is meant to be used as-is.
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


def tool_hold_payment(conn: sqlite3.Connection, payment_id: str, reason: str) -> dict:
    txn = conn.execute("SELECT amount FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone()
    amount = txn[0] if txn else None
    score = latest_risk_score(conn, payment_id)
    context = {"amount": amount, "risk_score": score["score"] if score else None}
    tier, rule = evaluate_policy(conn, "hold_payment", context)

    if tier == "auto":
        # TODO (Day 6): call razorpay_client.payment.fetch(payment_id) then
        # your own "hold" flag propagation (Razorpay itself has no native
        # "hold" endpoint — this is typically your own DB flag + a delayed
        # capture/refund decision, documented as a design choice, not hidden).
        conn.execute("UPDATE transactions SET status = status WHERE payment_id = ?", (payment_id,))  # placeholder no-op
        conn.commit()
        result = {"status": "held", "payment_id": payment_id}
        action_id = log_agent_action(
            conn, payment_id=payment_id, dispute_id=None, action_type="hold_payment",
            decision_tier="auto_executed", risk_score_at_decision=context["risk_score"],
            policy_rule_applied=rule, agent_reasoning=reason,
            tool_input={"payment_id": payment_id, "reason": reason}, tool_output=result, actor="agent",
        )
        result["agent_action_id"] = action_id
        return result

    result = {"status": "queued_for_approval" if tier == "approval_required" else "denied", "payment_id": payment_id}
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="hold_payment",
        decision_tier="queued_for_approval" if tier == "approval_required" else "denied",
        risk_score_at_decision=context["risk_score"], policy_rule_applied=rule,
        agent_reasoning=reason, tool_input={"payment_id": payment_id, "reason": reason},
        tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def tool_release_payment(conn: sqlite3.Connection, payment_id: str, reason: str) -> dict:
    score = latest_risk_score(conn, payment_id)
    context = {"risk_score": score["score"] if score else None}
    tier, rule = evaluate_policy(conn, "release_payment", context)
    decision_tier = "auto_executed" if tier == "auto" else ("queued_for_approval" if tier == "approval_required" else "denied")
    result = {"status": "released" if tier == "auto" else decision_tier, "payment_id": payment_id}
    # TODO (Day 6): clear your own hold flag / notify Razorpay-side workflow.
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="release_payment",
        decision_tier=decision_tier, risk_score_at_decision=context["risk_score"],
        policy_rule_applied=rule, agent_reasoning=reason,
        tool_input={"payment_id": payment_id, "reason": reason}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


def tool_draft_dispute_evidence(conn: sqlite3.Connection, dispute_id: str) -> dict:
    # Always auto — drafting has no money_impact (see tools_schema.json).
    dispute = conn.execute(
        "SELECT payment_id, reason_code, amount FROM disputes WHERE dispute_id = ?", (dispute_id,)
    ).fetchone()
    # TODO (Day 7): replace this template with an actual LLM call (Claude)
    # that pulls payment metadata + a policy/evidence template and drafts
    # summary + explanation_letter. Kept deterministic here for the demo.
    draft = {
        "summary": f"Evidence package for dispute {dispute_id}",
        "explanation_letter": (
            f"Payment {dispute[0] if dispute else '?'} was authorized and delivered per standard "
            f"process; reason code {dispute[1] if dispute else 'unknown'} is disputed on these grounds: [TODO fill]."
        ),
        "confidence": 0.5,
    }
    conn.execute("UPDATE disputes SET evidence_draft = ? WHERE dispute_id = ?", (json.dumps(draft), dispute_id))
    conn.commit()
    action_id = log_agent_action(
        conn, payment_id=dispute[0] if dispute else None, dispute_id=dispute_id,
        action_type="draft_dispute_evidence", decision_tier="auto_executed",
        risk_score_at_decision=None, policy_rule_applied="draft_evidence_always",
        agent_reasoning="Evidence drafting has no money impact; always auto-allowed.",
        tool_input={"dispute_id": dispute_id}, tool_output=draft, actor="agent",
    )
    draft["agent_action_id"] = action_id
    return draft


def tool_submit_dispute_evidence(conn: sqlite3.Connection, dispute_id: str, evidence: dict) -> dict:
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
    # TODO (Day 8): actually send via WhatsApp/email provider.
    result = {"status": "sent", "payment_id": payment_id}
    action_id = log_agent_action(
        conn, payment_id=payment_id, dispute_id=None, action_type="notify_merchant",
        decision_tier="auto_executed", risk_score_at_decision=None,
        policy_rule_applied="notify_merchant_always", agent_reasoning="Informational only, no money impact.",
        tool_input={"payment_id": payment_id, "message": message}, tool_output=result, actor="agent",
    )
    result["agent_action_id"] = action_id
    return result


# ============================================================================
# 4. CLAUDE AGENT SDK WIRING  (TODO — Day 4)
#    This is where the tool EXECUTION functions above get exposed to Claude
#    as callable tools, using the @tool decorator pattern from the Agent SDK
#    docs (https://code.claude.com/docs/en/agent-sdk/python). Left as a
#    documented stub so this file still runs with zero dependencies until
#    you `pip install claude-agent-sdk` and plug in ANTHROPIC_API_KEY.
# ============================================================================

async def run_agent(user_prompt: str) -> None:
    """
    TODO (Day 4): uncomment and complete. Sketch below matches the SDK's
    documented pattern — @tool decorator + create_sdk_mcp_server +
    can_use_tool permission handler wired to evaluate_policy().

    from claude_agent_sdk import (
        tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient,
        AssistantMessage, TextBlock, PermissionResultAllow, PermissionResultDeny,
    )

    conn = get_conn()

    @tool(name="get_risk_assessment", description="...", input_schema={"payment_id": str})
    async def _get_risk_assessment(args):
        return {"content": [{"type": "text", "text": json.dumps(tool_get_risk_assessment(conn, args["payment_id"]))}]}

    # ... one @tool wrapper per function above, each delegating to the
    # already-gated tool_* function so the SAME policy logic applies whether
    # Claude calls the tool or you call it directly in a test.

    risk_server = create_sdk_mcp_server(name="risk", version="0.1.0", tools=[
        _get_risk_assessment,  # , _hold_payment, _release_payment, ...
    ])

    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a payments risk agent for a Razorpay merchant. You may "
            "recommend and, where policy allows, execute actions on flagged "
            "transactions and disputes. Every action you take is logged with "
            "your reasoning. Never claim an action succeeded if the tool "
            "returned 'queued_for_approval' or 'denied' — report it honestly "
            "as pending human review."
        ),
        mcp_servers={"risk": risk_server},
        allowed_tools=["mcp__risk__get_risk_assessment"],  # add the rest as you wire them
        permission_mode="dontAsk",
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
    """
    raise NotImplementedError("Wire this up on Day 4 — see docstring above.")


# ============================================================================
# 5. SELF-CONTAINED DEMO — proves the gating + audit chain actually work
# ============================================================================

def run_demo() -> None:
    init_db(fresh=True)
    conn = get_conn()

    now = int(time.time())
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_demo_mid', 'order_demo_mid', 50000, 'INR', 'captured', 'card', 1, 'ok@example.com', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_demo_high', 'order_demo_high', 1500000, 'INR', 'captured', 'card', 1, 'risky@example.com', ?)", (now,)
    )
    # score 0.55 -> hits 'mid_risk_small_amount_hold' (0.4 <= score < 0.75, amount <= 1,000,000) -> auto
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_demo_mid', 0.55, 'hybrid-v0.1', '[\"new_email\"]', '{}', 'hybrid')"
    )
    # score 0.91, amount > 1,000,000 -> hits BOTH 'high_risk_hold' and 'large_amount_hold' -> approval_required either way
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_demo_high', 0.91, 'hybrid-v0.1', '[\"velocity_high\",\"amount_outlier\"]', '{}', 'hybrid')"
    )
    conn.commit()

    print("--- Mid risk (0.55), small amount (Rs.500): expect auto_executed ---")
    print(tool_hold_payment(conn, "pay_demo_mid", "Testing mid-risk auto-hold path"))

    print("\n--- High risk (0.91), large amount (Rs.15,000): expect queued_for_approval ---")
    print(tool_hold_payment(conn, "pay_demo_high", "Velocity spike + amount outlier detected"))

    print("\n--- Note: a genuinely LOW-risk hold_payment call (score < 0.4) has NO matching")
    print("    'auto' rule in policy_config, so it correctly fails safe to approval_required")
    print("    rather than silently defaulting to allow. This is intentional -- see")
    print("    evaluate_policy()'s fail-safe default and ARCHITECTURE.md.")

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