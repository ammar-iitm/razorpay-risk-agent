"""
day7/verify_live_hold.py — Day 7 entry point: proves tool_hold_payment /
tool_release_payment (agent/agent_tools.py) actually check LIVE Razorpay
status now, not just local DB state.

Same "prove it against something real, not just seeded fake data" instinct
as day2/fetch_payment.py and day6/run_scenario.py --live: this script does
NOT seed a fake payment_id. It takes a REAL payment id from a checkout you
actually completed (day2/checkout.html, same as Day 2), fetches it live from
Razorpay to build a real transactions row (mirroring day2/fetch_payment.py's
own field mapping so there's one definition of "how a payment maps onto our
schema," not two), inserts a test risk score, then calls the real gated tool
functions and shows you the live-verification note that lands in
agent_reasoning plus the on_hold/held_at columns actually flipping in SQLite.

Why this can't be fully automated end-to-end like Day 6's scenario: Day 6
could seed synthetic transactions because it was testing POLICY LOGIC, which
doesn't care whether a payment is "real." This script is testing LIVE API
INTEGRATION, which only means something against a payment that genuinely
exists on Razorpay's servers — and completing checkout requires a human in
a browser, same reason Day 2 needed you to click through checkout.html
yourself.

Requires RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in your environment (same
test-mode keys as Day 2). Without them, this script tells you so and exits
cleanly rather than silently doing nothing useful.

Run:
  1. Serve + open day2/checkout.html, complete a test payment, copy the
     pay_... id it shows you.
  2. python3 day7/verify_live_hold.py pay_XXXXXXXXXXXXXX
"""

import os
import sys
import time

# Use a dedicated DB file for this script so it never touches whatever
# risk_agent.db you've been using for --demo / day6 runs — set BEFORE
# importing agent_tools, since it reads RISK_AGENT_DB at import time.
os.environ.setdefault(
    "RISK_AGENT_DB",
    os.path.join(os.path.dirname(__file__), "..", "risk_agent_day7_verify.db"),
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from agent_tools import get_conn, init_db, tool_hold_payment, tool_release_payment, DB_PATH  # noqa: E402
import razorpay_client  # noqa: E402


def seed_from_live_payment(conn, payment_id: str) -> dict:
    """Fetch the payment for real and insert a transactions row from it —
    the actual live data, not a guess at what it might look like."""
    payment = razorpay_client.fetch_payment(payment_id)
    if payment is None:
        print(f"Could not fetch '{payment_id}' from Razorpay. Check the id is a real "
              f"pay_... id from a completed test checkout, and that RAZORPAY_KEY_ID / "
              f"RAZORPAY_KEY_SECRET are set to the same test-mode keys used to create it.")
        sys.exit(1)

    card = payment.get("card") or {}
    conn.execute(
        """INSERT OR REPLACE INTO transactions
           (payment_id, order_id, amount, currency, status, method, captured,
            email, contact, card_network, card_last4, vpa, bank,
            error_code, error_description, error_reason, razorpay_created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            payment.get("id"), payment.get("order_id"), payment.get("amount"),
            payment.get("currency"), payment.get("status"), payment.get("method"),
            int(bool(payment.get("captured"))), payment.get("email"), payment.get("contact"),
            card.get("network"), card.get("last4"), payment.get("vpa"), payment.get("bank"),
            payment.get("error_code"), payment.get("error_description"), payment.get("error_reason"),
            payment.get("created_at"),
        ),
    )
    # A test score high enough to hit the 'auto' hold tier (see Day 5's
    # evidence for why 0.8 is the real threshold, not a round number).
    conn.execute(
        """INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source)
           VALUES (?, 0.85, 'day7-live-verify', '["manual_test"]', '{}', 'rule_engine')""",
        (payment_id,),
    )
    conn.commit()
    print(f"Seeded real transaction from Razorpay: status={payment.get('status')}, "
          f"amount={payment.get('amount')} {payment.get('currency')}, method={payment.get('method')}")
    return payment


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("pay_"):
        print("Usage: python3 day7/verify_live_hold.py pay_XXXXXXXXXXXXXX")
        print("(get a real pay_... id by completing a test payment via day2/checkout.html)")
        sys.exit(1)
    payment_id = sys.argv[1]

    if not razorpay_client.credentials_configured():
        print("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET aren't set to valid test-mode keys "
              "(must start with rzp_test_). Live verification can't run without them — "
              "this is the exact same soft-fail path --demo relies on, just surfaced "
              "explicitly here instead of silently skipped.")
        sys.exit(1)

    init_db(fresh=True)
    conn = get_conn()

    seed_from_live_payment(conn, payment_id)

    print("\n--- Calling tool_hold_payment (should fetch live status, then apply policy) ---")
    hold_result = tool_hold_payment(conn, payment_id, "Day 7 live verification run")
    print(hold_result)

    row = conn.execute("SELECT status, on_hold, held_at FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone()
    print(f"DB state after hold: status={row[0]}, on_hold={row[1]}, held_at={row[2]}")

    action = conn.execute(
        "SELECT agent_reasoning FROM agent_actions WHERE payment_id = ? ORDER BY id DESC LIMIT 1", (payment_id,)
    ).fetchone()
    print(f"agent_reasoning (should mention live status): {action[0]!r}")

    print("\n--- Calling tool_release_payment (fetches live status again, then applies policy) ---")
    release_result = tool_release_payment(conn, payment_id, "Day 7 live verification run — releasing")
    print(release_result)
    if release_result["status"] != "released":
        print(
            "NOTE: this is expected, not a bug. This script seeds a 0.85 test risk score "
            "specifically so the hold hits the 'auto' tier — but policy_config's "
            "'release_after_review' rule only auto-releases BELOW 0.8. A payment held for "
            "looking high-risk correctly requires a human to approve releasing it; the same "
            "system that flagged it doesn't get to silently clear itself. See BUILD_LOG.md's "
            "Day 1 entry for the same fail-safe pattern on synthetic data."
        )

    row = conn.execute("SELECT status, on_hold FROM transactions WHERE payment_id = ?", (payment_id,)).fetchone()
    print(f"DB state after release: status={row[0]}, on_hold={row[1]}")

    print(f"\nDone. Full audit trail is in {DB_PATH} (agent_actions table) if you want to inspect it further.")


if __name__ == "__main__":
    main()
