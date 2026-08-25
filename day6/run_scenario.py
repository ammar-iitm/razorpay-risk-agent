"""
day6/run_scenario.py — Day 6 entry point: proves the Agent SDK orchestrator
in agent/agent_tools.py's run_agent() actually works, the same two-tier way
day1/calculator_with_gate.py proved the permission-handler mechanism:

  1. verify_handler_offline() — calls _validate_tool_input() directly with
     fake tool calls. Zero API cost, proves the input-validation LOGIC
     (malformed payment_id/dispute_id gets denied) is correct.
  2. main() — seeds two realistic transactions + one dispute into a fresh
     DB, then runs the REAL live agent loop and watches Claude decide what
     to do with them using the actual gated tools. Proves the WIRING works.

Run:
  python3 day6/run_scenario.py            (offline check only)
  python3 day6/run_scenario.py --live     (offline check + live agent run)
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from agent_tools import (  # noqa: E402
    get_conn, init_db, run_agent, verify_audit_chain, _validate_tool_input,
)


def verify_handler_offline() -> None:
    """Zero-cost, zero-API-call check that _validate_tool_input's LOGIC is
    correct, before trusting it in a live run."""

    async def _run() -> None:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        bad_payment = await _validate_tool_input("mcp__risk__hold_payment", {"payment_id": "not_a_real_id", "reason": "test"}, None)
        good_payment = await _validate_tool_input("mcp__risk__hold_payment", {"payment_id": "pay_abc123", "reason": "test"}, None)
        bad_dispute = await _validate_tool_input("mcp__risk__accept_dispute", {"dispute_id": "12345", "reason": "test"}, None)
        good_dispute = await _validate_tool_input("mcp__risk__accept_dispute", {"dispute_id": "disp_abc123", "reason": "test"}, None)
        no_id_at_all = await _validate_tool_input("mcp__risk__notify_merchant", {"payment_id": "pay_x", "message": "hi"}, None)

        print("--- Offline permission-handler check (no API calls) ---")
        print("malformed payment_id  ->", type(bad_payment).__name__, "|", getattr(bad_payment, "message", ""))
        print("real-looking pay_...   ->", type(good_payment).__name__)
        print("malformed dispute_id  ->", type(bad_dispute).__name__, "|", getattr(bad_dispute, "message", ""))
        print("real-looking disp_...  ->", type(good_dispute).__name__)
        print("unrelated valid call   ->", type(no_id_at_all).__name__)

        assert isinstance(bad_payment, PermissionResultDeny), "malformed payment_id should have been DENIED"
        assert isinstance(good_payment, PermissionResultAllow), "well-formed pay_... id should have been ALLOWED"
        assert isinstance(bad_dispute, PermissionResultDeny), "malformed dispute_id should have been DENIED"
        assert isinstance(good_dispute, PermissionResultAllow), "well-formed disp_... id should have been ALLOWED"
        assert isinstance(no_id_at_all, PermissionResultAllow), "a normal, well-formed call should have been ALLOWED"
        print("PASS: handler denies exactly the malformed-id cases, and only those.")

    asyncio.run(_run())


def seed_scenario_data() -> None:
    """Fresh DB with two transactions (one that should auto-hold, one that
    needs approval) and one open dispute — realistic enough for the live
    agent to have real decisions to make, not a trivial single-tool call."""
    init_db(fresh=True)
    conn = get_conn()
    now = int(time.time())

    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_scenario_mid', 'order_scenario_mid', 80000, 'INR', 'captured', 'card', 1, 'newcustomer@example.com', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_scenario_mid', 0.85, 'hybrid-v0.1', '[\"is_new_email\",\"txns_last_1h_same_email\"]', '{}', 'rule_engine')"
    )

    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_scenario_high', 'order_scenario_high', 1800000, 'INR', 'captured', 'card', 1, 'risky@example.com', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES ('pay_scenario_high', 0.93, 'hybrid-v0.1', '[\"amount_zscore_high\",\"txns_last_24h_same_card\"]', '{}', 'rule_engine')"
    )

    conn.execute(
        "INSERT INTO disputes (dispute_id, payment_id, amount, currency, reason_code, phase, status, respond_by, razorpay_created_at) "
        "VALUES ('disp_scenario_1', 'pay_scenario_high', 1800000, 'INR', 'goods_or_services_not_provided', 'chargeback', 'open', ?, ?)",
        (now + 7 * 86400, now),
    )
    conn.commit()
    conn.close()


SCENARIO_PROMPT = """\
Two payments need review, and there's one open dispute:

1. pay_scenario_mid — a card payment from a brand-new customer email.
2. pay_scenario_high — a much larger card payment flagged for velocity and amount anomalies.
3. disp_scenario_1 — an open chargeback dispute on pay_scenario_high, reason: goods_or_services_not_provided.

For each payment: check its risk assessment, then decide whether to hold it, explaining your reasoning.
For the dispute: draft evidence (do not submit it — that always needs a human).
Finally, send the merchant one notification summarizing what happened across all three, being explicit
about which actions actually executed versus which are waiting on human approval.
"""


def main() -> None:
    seed_scenario_data()
    conn = get_conn()
    print("--- Live agent run (real API call) ---")
    asyncio.run(run_agent(SCENARIO_PROMPT, conn=conn, max_turns=12))

    print("\n--- Verifying audit chain after the live run ---")
    ok, bad_id = verify_audit_chain(conn)
    print(f"Chain intact: {ok}")
    print("\n--- Full agent_actions log from this run ---")
    for row in conn.execute(
        "SELECT id, action_type, decision_tier, policy_rule_applied, payment_id, dispute_id FROM agent_actions ORDER BY id"
    ).fetchall():
        print(row)
    conn.close()


if __name__ == "__main__":
    verify_handler_offline()
    if "--live" in sys.argv:
        print()
        main()
    else:
        print("\n(Skipping live run — pass --live to also exercise the real agent loop.)")
