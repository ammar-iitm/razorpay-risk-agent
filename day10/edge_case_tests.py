"""
day10/edge_case_tests.py — a maximal edge-case pass against the real code,
run against a scratch database (never risk_agent.db). Every case below is
actually executed, not reasoned about — a PASS/FAIL/BUG line is printed for
each. Anything marked BUG was a real crash or wrong behavior found this way;
see docs/BUILD_LOG.md for what got fixed as a result and docs/FAILURE_MODES.md
for the curated summary.

Run: python3 day10/edge_case_tests.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
import agent_tools  # noqa: E402
import notify_channel  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, "PASS", None))
    except AssertionError as e:
        RESULTS.append((name, "BUG", str(e)))
    except Exception as e:
        RESULTS.append((name, "BUG", f"{type(e).__name__}: {e}"))


def fresh_conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    os.environ["RISK_AGENT_DB"] = path
    import importlib
    importlib.reload(agent_tools)
    agent_tools.init_db(fresh=True)
    return agent_tools.get_conn(), path


def seed_one(conn, payment_id="pay_edge_test", amount=50000, score=0.85):
    now = 1700000000
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES (?, ?, ?, 'INR', 'captured', 'card', 1, 'x@example.com', ?)",
        (payment_id, payment_id + "_order", amount, now),
    )
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES (?, ?, 'hybrid-v0.1', '[]', '{}', 'hybrid')",
        (payment_id, score),
    )
    conn.commit()


# ============================================================================
# 1. Agent tool input edge cases
# ============================================================================

def t_negative_amount():
    conn, path = fresh_conn()
    seed_one(conn, "pay_neg", amount=-50000, score=0.9)
    r = agent_tools.tool_hold_payment(conn, "pay_neg", "test negative amount")
    assert r.get("status") in ("held", "queued_for_approval", "denied"), f"unexpected: {r}"
    conn.close(); os.remove(path)


def t_zero_amount():
    conn, path = fresh_conn()
    seed_one(conn, "pay_zero", amount=0, score=0.85)
    r = agent_tools.tool_hold_payment(conn, "pay_zero", "test zero amount")
    assert r.get("status") == "held", f"expected held (0 <= 1,000,000): {r}"
    conn.close(); os.remove(path)


def t_huge_amount():
    conn, path = fresh_conn()
    seed_one(conn, "pay_huge", amount=10**15, score=0.99)
    r = agent_tools.tool_hold_payment(conn, "pay_huge", "test huge amount")
    assert r.get("status") == "queued_for_approval", f"expected queued (amount > 1M): {r}"
    conn.close(); os.remove(path)


def t_empty_payment_id():
    conn, path = fresh_conn()
    r = agent_tools.tool_hold_payment(conn, "", "test empty id")
    assert r.get("status") == "not_found", f"expected not_found for empty id: {r}"
    conn.close(); os.remove(path)


def t_none_payment_id():
    conn, path = fresh_conn()
    r = agent_tools.tool_hold_payment(conn, None, "test None id")
    assert r.get("status") == "not_found", f"expected not_found for None id: {r}"
    conn.close(); os.remove(path)


def t_sql_injection_payment_id():
    conn, path = fresh_conn()
    seed_one(conn, "pay_safe")
    evil = "pay_x'; DROP TABLE transactions; --"
    r = agent_tools.tool_hold_payment(conn, evil, "test sqli id")
    assert r.get("status") == "not_found", f"expected not_found: {r}"
    # confirm the table really is still there and untouched
    still_there = conn.execute("SELECT 1 FROM transactions WHERE payment_id = 'pay_safe'").fetchone()
    assert still_there is not None, "transactions table was damaged by an injection-shaped id!"
    conn.close(); os.remove(path)


def t_very_long_payment_id():
    conn, path = fresh_conn()
    long_id = "pay_" + ("a" * 100000)
    r = agent_tools.tool_hold_payment(conn, long_id, "test long id")
    assert r.get("status") == "not_found", f"expected not_found: {r}"
    conn.close(); os.remove(path)


def t_unicode_payment_id():
    conn, path = fresh_conn()
    r = agent_tools.tool_hold_payment(conn, "pay_🔥emoji_测试", "test unicode id")
    assert r.get("status") == "not_found", f"expected not_found: {r}"
    conn.close(); os.remove(path)


def t_double_hold():
    conn, path = fresh_conn()
    seed_one(conn, "pay_dh", amount=50000, score=0.85)
    r1 = agent_tools.tool_hold_payment(conn, "pay_dh", "first hold")
    r2 = agent_tools.tool_hold_payment(conn, "pay_dh", "second hold, already held")
    assert r1["status"] == "held" and r2["status"] == "held", f"double-hold results: {r1}, {r2}"
    row = conn.execute("SELECT on_hold FROM transactions WHERE payment_id='pay_dh'").fetchone()
    assert row[0] == 1, "on_hold should still be 1 after a second hold call"
    n = conn.execute("SELECT COUNT(*) FROM agent_actions WHERE payment_id='pay_dh'").fetchone()[0]
    assert n == 2, f"expected 2 separate audit rows (both are real decisions), got {n}"
    conn.close(); os.remove(path)


def t_release_never_held():
    conn, path = fresh_conn()
    seed_one(conn, "pay_rnh", amount=50000, score=0.5)
    r = agent_tools.tool_release_payment(conn, "pay_rnh", "release something never held")
    assert r.get("status") in ("released", "queued_for_approval", "denied"), f"unexpected: {r}"
    conn.close(); os.remove(path)


def t_double_accept_dispute():
    conn, path = fresh_conn()
    seed_one(conn, "pay_dd")
    conn.execute(
        "INSERT INTO disputes (dispute_id, payment_id, amount, currency, reason_code, phase, status, respond_by, razorpay_created_at) "
        "VALUES ('disp_dd', 'pay_dd', 50000, 'INR', 'x', 'chargeback', 'open', 1700100000, 1700000000)"
    )
    conn.commit()
    r1 = agent_tools.tool_accept_dispute(conn, "disp_dd", "first accept")
    r2 = agent_tools.tool_accept_dispute(conn, "disp_dd", "second accept, already recommended")
    assert r1["status"] == "queued_for_approval" and r2["status"] == "queued_for_approval", f"{r1}, {r2}"
    conn.close(); os.remove(path)


def t_submit_evidence_without_draft():
    conn, path = fresh_conn()
    seed_one(conn, "pay_sw")
    conn.execute(
        "INSERT INTO disputes (dispute_id, payment_id, amount, currency, reason_code, phase, status, respond_by, razorpay_created_at) "
        "VALUES ('disp_sw', 'pay_sw', 50000, 'INR', 'x', 'chargeback', 'open', 1700100000, 1700000000)"
    )
    conn.commit()
    # never called tool_draft_dispute_evidence first
    r = agent_tools.tool_submit_dispute_evidence(conn, "disp_sw", {"summary": "no real draft exists"})
    assert r.get("status") == "queued_for_approval", f"unexpected: {r}"
    conn.close(); os.remove(path)


def t_xss_in_reason_stored_raw():
    """Confirms the STORAGE layer keeps the raw text (no crash, no silent
    mutation) -- escaping is the rendering layer's job (Jinja2 autoescape),
    tested separately in the dashboard section below."""
    conn, path = fresh_conn()
    seed_one(conn, "pay_xss", amount=50000, score=0.85)
    payload = "<script>alert(1)</script>"
    r = agent_tools.tool_hold_payment(conn, "pay_xss", payload)
    stored = conn.execute(
        "SELECT agent_reasoning FROM agent_actions WHERE payment_id='pay_xss'"
    ).fetchone()[0]
    assert payload in stored, "raw reasoning text should be stored verbatim, unescaped, in the db"
    conn.close(); os.remove(path)


# ============================================================================
# 2. Audit chain edge cases
# ============================================================================

def t_empty_audit_chain():
    conn, path = fresh_conn()
    ok, bad = agent_tools.verify_audit_chain(conn)
    assert ok is True and bad is None, f"empty chain should verify as intact: {ok}, {bad}"
    conn.close(); os.remove(path)


def t_single_row_audit_chain():
    conn, path = fresh_conn()
    seed_one(conn, "pay_single", amount=50000, score=0.85)
    agent_tools.tool_hold_payment(conn, "pay_single", "only action")
    ok, bad = agent_tools.verify_audit_chain(conn)
    assert ok is True, f"single real row should verify intact: {ok}, {bad}"
    conn.close(); os.remove(path)


def t_tamper_last_row_detected():
    conn, path = fresh_conn()
    seed_one(conn, "pay_t1", amount=50000, score=0.85)
    seed_one(conn, "pay_t2", amount=60000, score=0.85)
    agent_tools.tool_hold_payment(conn, "pay_t1", "action 1")
    agent_tools.tool_hold_payment(conn, "pay_t2", "action 2")
    last_id = conn.execute("SELECT MAX(id) FROM agent_actions").fetchone()[0]
    conn.execute("UPDATE agent_actions SET agent_reasoning='tampered' WHERE id=?", (last_id,))
    conn.commit()
    ok, bad = agent_tools.verify_audit_chain(conn)
    assert ok is False and bad == last_id, f"expected break at last row {last_id}: {ok}, {bad}"
    conn.close(); os.remove(path)


def t_tamper_middle_row_breaks_everything_after():
    conn, path = fresh_conn()
    for i in range(4):
        seed_one(conn, f"pay_mid{i}", amount=50000, score=0.85)
        agent_tools.tool_hold_payment(conn, f"pay_mid{i}", f"action {i}")
    conn.execute("UPDATE agent_actions SET agent_reasoning='tampered' WHERE id=2")
    conn.commit()
    ok, bad = agent_tools.verify_audit_chain(conn)
    assert ok is False and bad == 2, f"expected break reported at row 2: {ok}, {bad}"
    conn.close(); os.remove(path)


# ============================================================================
# 3. Policy engine boundary conditions
# ============================================================================

def t_boundary_score_exactly_0_8():
    conn, path = fresh_conn()
    seed_one(conn, "pay_b1", amount=50000, score=0.8)  # exactly at ">=0.8"
    r = agent_tools.tool_hold_payment(conn, "pay_b1", "boundary score test")
    assert r["status"] == "held", f"0.8 should hit mid_risk auto rule (>=0.8): {r}"
    conn.close(); os.remove(path)


def t_boundary_score_just_below_0_8():
    conn, path = fresh_conn()
    seed_one(conn, "pay_b2", amount=50000, score=0.7999999)
    r = agent_tools.tool_hold_payment(conn, "pay_b2", "boundary score test")
    assert r["status"] == "queued_for_approval", f"just below 0.8 should fail safe: {r}"
    conn.close(); os.remove(path)


def t_boundary_amount_exactly_1000000():
    conn, path = fresh_conn()
    seed_one(conn, "pay_b3", amount=1000000, score=0.9)  # exactly at "<=1000000" AND NOT ">1000000"
    r = agent_tools.tool_hold_payment(conn, "pay_b3", "boundary amount test")
    assert r["status"] == "held", f"amount==1,000,000 should hit mid_risk (<=1M), not large_amount (>1M): {r}"
    conn.close(); os.remove(path)


def t_boundary_amount_1000001():
    conn, path = fresh_conn()
    seed_one(conn, "pay_b4", amount=1000001, score=0.9)
    r = agent_tools.tool_hold_payment(conn, "pay_b4", "boundary amount test")
    assert r["status"] == "queued_for_approval", f"amount==1,000,001 should hit large_amount rule: {r}"
    conn.close(); os.remove(path)


def t_no_risk_score_at_all():
    conn, path = fresh_conn()
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES ('pay_noscore', 'o', 50000, 'INR', 'captured', 'card', 1, 'x@example.com', 1700000000)"
    )
    conn.commit()
    r = agent_tools.tool_hold_payment(conn, "pay_noscore", "never scored")
    assert r["status"] == "queued_for_approval", f"unscored payment should fail safe, not auto-hold: {r}"
    conn.close(); os.remove(path)


def t_concurrent_writers_dont_break_the_chain():
    """Two connections racing to log_agent_action() used to both read the
    same "last hash" before either committed (a SELECT never blocks a
    writer), so the second writer's this_hash got computed from an
    already-stale prev_hash -- verify_audit_chain() then reported that as
    tampering that never actually happened. Found with real threads, not a
    manual simulation: 5/5 trials broke the chain before the fix. Fixed by
    wrapping the read+insert in one BEGIN IMMEDIATE transaction so a second
    writer's own BEGIN IMMEDIATE blocks until the first commits. This test
    fires 12 real threads, each on its own connection, at the same
    payment_id and asserts the chain still verifies intact afterward."""
    conn, path = fresh_conn()
    seed_one(conn, "pay_race", amount=50000, score=0.85)
    conn.close()

    N = 12
    errors = []

    def worker(i):
        try:
            c = agent_tools.get_conn()
            agent_tools.log_agent_action(
                c, payment_id="pay_race", dispute_id=None, action_type="notify_merchant",
                decision_tier="auto_executed", risk_score_at_decision=None,
                policy_rule_applied=f"race_{i}", agent_reasoning=f"writer {i}",
                tool_input={"i": i}, tool_output={}, actor="agent",
            )
            c.close()
        except Exception as e:
            errors.append((i, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"writer thread(s) raised: {errors}"
    verify_conn = agent_tools.get_conn()
    row_count = verify_conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
    ok, bad_row = agent_tools.verify_audit_chain(verify_conn)
    assert row_count == N, f"expected {N} rows from {N} racing writers, got {row_count}"
    assert ok is True, f"chain should verify intact -- no tampering ever happened: bad_row={bad_row}"
    verify_conn.close()
    os.remove(path)


def t_unknown_action_type_fails_safe():
    conn, path = fresh_conn()
    tier, rule = agent_tools.evaluate_policy(conn, "delete_everything", {"amount": 1})
    assert tier == "approval_required" and rule == "default_fail_safe", f"unknown action_type: {tier}, {rule}"
    conn.close(); os.remove(path)


def t_malformed_operator_in_condition_fails_safe():
    """A typo'd operator (e.g. '=>' instead of '>=') in a hand-edited
    policy_config row used to KeyError the whole evaluate_policy() call --
    found by actually inserting one and calling it. Fixed: an unrecognized
    operator makes that clause not match rather than crash, so a malformed
    rule just never fires and the action correctly falls through to
    evaluate_policy()'s own approval_required default instead of taking
    down the tool call that triggered it."""
    conn, path = fresh_conn()
    conn.execute("UPDATE policy_config SET is_active = 0 WHERE action_type = 'hold_payment'")
    conn.execute(
        "INSERT INTO policy_config (rule_name, action_type, condition_json, autonomy_tier) "
        "VALUES ('typo_rule', 'hold_payment', '{\"risk_score\":{\"=>\":0.8}}', 'auto')"
    )
    conn.commit()
    tier, rule = agent_tools.evaluate_policy(conn, "hold_payment", {"risk_score": 0.9, "amount": 100})
    assert tier == "approval_required" and rule == "default_fail_safe", f"malformed operator: {tier}, {rule}"
    conn.close(); os.remove(path)


def t_smtp_port_non_numeric_soft_fails():
    """SMTP_PORT='not-a-number' used to raise an uncaught ValueError out of
    send_merchant_email(), contradicting its own docstring promise that a
    misconfiguration always returns sent=False rather than raising -- found
    by actually setting the env var and calling it. Fixed: the int(PORT)
    parse now lives inside the same try/except as the rest of the send."""
    env_keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "MERCHANT_EMAIL_TO"]
    saved = {k: os.environ.get(k) for k in env_keys}
    try:
        os.environ.update({
            "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "not-a-number",
            "SMTP_USER": "u", "SMTP_PASSWORD": "p", "SMTP_FROM": "a@example.com",
            "MERCHANT_EMAIL_TO": "b@example.com",
        })
        r = notify_channel.send_merchant_email("subj", "body")
        assert r == {"sent": False, "channel": "email",
                     "detail": "send failed: invalid literal for int() with base 10: 'not-a-number'"}, r
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ============================================================================
# Run everything
# ============================================================================

CASES = [
    ("negative amount", t_negative_amount),
    ("zero amount", t_zero_amount),
    ("huge amount (10^15)", t_huge_amount),
    ("empty string payment_id", t_empty_payment_id),
    ("None payment_id", t_none_payment_id),
    ("SQL-injection-shaped payment_id", t_sql_injection_payment_id),
    ("100k-char payment_id", t_very_long_payment_id),
    ("unicode/emoji payment_id", t_unicode_payment_id),
    ("double hold_payment (idempotent-ish)", t_double_hold),
    ("release a payment never held", t_release_never_held),
    ("double accept_dispute", t_double_accept_dispute),
    ("submit_dispute_evidence with no prior draft", t_submit_evidence_without_draft),
    ("XSS-shaped reason text stored raw", t_xss_in_reason_stored_raw),
    ("empty audit chain verifies intact", t_empty_audit_chain),
    ("single-row audit chain verifies intact", t_single_row_audit_chain),
    ("tamper last row -> detected", t_tamper_last_row_detected),
    ("tamper middle row -> detected at that row", t_tamper_middle_row_breaks_everything_after),
    ("12 real threads racing to log_agent_action -> chain stays intact", t_concurrent_writers_dont_break_the_chain),
    ("risk_score exactly 0.8 (boundary)", t_boundary_score_exactly_0_8),
    ("risk_score just below 0.8 (boundary)", t_boundary_score_just_below_0_8),
    ("amount exactly 1,000,000 (boundary)", t_boundary_amount_exactly_1000000),
    ("amount 1,000,001 (boundary)", t_boundary_amount_1000001),
    ("payment with no risk score at all", t_no_risk_score_at_all),
    ("unknown action_type fails safe", t_unknown_action_type_fails_safe),
    ("malformed operator in condition_json fails safe", t_malformed_operator_in_condition_fails_safe),
    ("SMTP_PORT non-numeric soft-fails instead of raising", t_smtp_port_non_numeric_soft_fails),
]

if __name__ == "__main__":
    for name, fn in CASES:
        check(name, fn)

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
