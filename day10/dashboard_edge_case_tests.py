"""
day10/dashboard_edge_case_tests.py — real HTTP-level fuzzing of
day9/dashboard.py's Flask routes via Flask's test client, run against a
scratch database (never risk_agent.db). Covers the two real crash
sequences found and fixed earlier in the Day 10 edge-case sweep (a
never-seeded db hitting /repair then /tamper) plus the stats strip and
hash-chain visualization added afterward: single-row chains, 20-row
chains, tampering a middle row and counting exactly which blocks should
flip, and negative-amount transactions flowing into the stats math.

Run: python3 day10/dashboard_edge_case_tests.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "day9"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, "PASS", None))
    except AssertionError as e:
        RESULTS.append((name, "BUG", str(e)))
    except Exception as e:
        RESULTS.append((name, "BUG", f"{type(e).__name__}: {e}"))


def fresh_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    os.environ["RISK_AGENT_DB"] = path
    import agent_tools
    import dashboard
    importlib.reload(agent_tools)
    importlib.reload(dashboard)
    return dashboard.app.test_client(), agent_tools, path


def seed_one(agent_tools, conn, payment_id, amount, score, reason="test"):
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, email, razorpay_created_at) "
        "VALUES (?, ?, ?, 'INR', 'captured', 'card', 1, 'x@example.com', 1700000000)",
        (payment_id, payment_id + "_o", amount),
    )
    conn.execute(
        "INSERT INTO risk_scores (payment_id, score, model_version, reason_codes, feature_snapshot, scoring_source) "
        "VALUES (?, ?, 'v', '[]', '{}', 'hybrid')", (payment_id, score),
    )
    conn.commit()
    agent_tools.tool_hold_payment(conn, payment_id, reason)


def count_blocks(html, cls):
    return html.count(f'class="chain-block {cls}"')


def count_links(html):
    return html.count('<div class="chain-link')


def t_crash_sequence_repair_then_tamper_before_seed():
    """The exact real-world click order that used to crash this app twice
    in a row (found and fixed earlier this Day-10 pass): a fresh visitor
    clicks 'Sync hold state' (always visible in FEED_BODY) before ever
    seeding, then 'Tamper row 1' (always visible in AUDIT_BODY) right
    after."""
    client, agent_tools, path = fresh_client()
    assert client.get("/").status_code == 200
    assert client.post("/repair").status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/audit").status_code == 200
    assert client.post("/tamper").status_code == 302
    assert client.get("/audit").status_code == 200
    os.remove(path)


def t_single_row_chain_visual():
    client, agent_tools, path = fresh_client()
    agent_tools.init_db(fresh=True)
    conn = agent_tools.get_conn()
    seed_one(agent_tools, conn, "pay_one", 50000, 0.85)
    conn.close()
    html = client.get("/audit").get_data(as_text=True)
    assert count_blocks(html, "ok") == 1, f"expected 1 ok block, got {count_blocks(html, 'ok')}"
    assert count_links(html) == 0, f"single row shouldn't have any link divs, got {count_links(html)}"
    os.remove(path)


def t_negative_amount_in_stats():
    client, agent_tools, path = fresh_client()
    agent_tools.init_db(fresh=True)
    conn = agent_tools.get_conn()
    seed_one(agent_tools, conn, "pay_pos", 50000, 0.85)
    seed_one(agent_tools, conn, "pay_neg", -30000, 0.9)
    conn.close()
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Rs 200" in html, f"expected net Rs 200 (500 - 300) in the value-on-hold stat: {html[:2000]}"
    os.remove(path)


def t_twenty_row_chain_and_midpoint_tamper():
    client, agent_tools, path = fresh_client()
    agent_tools.init_db(fresh=True)
    conn = agent_tools.get_conn()
    for i in range(20):
        seed_one(agent_tools, conn, f"pay_many{i}", 50000, 0.85, reason=f"action {i}")
    conn.close()

    html = client.get("/audit").get_data(as_text=True)
    assert count_blocks(html, "ok") == 20, f"expected 20 ok blocks, got {count_blocks(html, 'ok')}"
    assert count_links(html) == 19, f"expected 19 links for 20 rows, got {count_links(html)}"
    assert count_blocks(html, "broken") == 0

    conn = agent_tools.get_conn()
    conn.execute("UPDATE agent_actions SET agent_reasoning='tampered mid' WHERE id=10")
    conn.commit()
    conn.close()

    html = client.get("/audit").get_data(as_text=True)
    assert "BROKEN at row id 10" in html
    assert count_blocks(html, "broken") == 11, f"expected exactly rows 10-20 (11 blocks) broken, got {count_blocks(html, 'broken')}"
    assert count_blocks(html, "ok") == 9, f"expected exactly rows 1-9 (9 blocks) ok, got {count_blocks(html, 'ok')}"
    os.remove(path)


def t_full_normal_flow_end_to_end():
    client, agent_tools, path = fresh_client()
    assert client.post("/seed").status_code == 302
    html = client.get("/").get_data(as_text=True)
    assert "pay_demo_mid" in html and "pay_demo_high" in html
    assert "Currently on hold" in html
    html = client.get("/audit").get_data(as_text=True)
    assert "Chain intact" in html
    assert count_blocks(html, "broken") == 0
    assert client.get("/metrics").status_code == 200
    os.remove(path)


CASES = [
    ("crash sequence: repair then tamper before any seed", t_crash_sequence_repair_then_tamper_before_seed),
    ("single-row audit chain visual", t_single_row_chain_visual),
    ("negative-amount transaction in stats strip", t_negative_amount_in_stats),
    ("20-row chain + tamper at row 10 -> exactly 11 blocks red", t_twenty_row_chain_and_midpoint_tamper),
    ("full normal flow end to end", t_full_normal_flow_end_to_end),
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
