"""
day4/feature_engineering.py — computes the four precomputed feature columns
in sql/schema.sql's `transactions` table (txns_last_1h_same_email,
txns_last_24h_same_card, is_new_email, amount_zscore_for_method) from
Razorpay's actual payment fields.

Why this file exists — the PaySim-to-Razorpay signal gap:
Day 3's strongest PaySim signal (origin_drained_to_zero) needed before/after
ACCOUNT BALANCES. Razorpay is a payment gateway, not a bank ledger — the
real payment payload verified in Day 2 (fetch_payment.py) has no balance
fields at all, on either side. That specific signal doesn't exist in this
project's real data and can't be ported, full stop.

What actually transfers from Day 3's findings, and what replaces the rest:
  - PaySim's `amount` signal (fraud skews higher) DOES transfer — Razorpay
    payments have a real `amount` field. Implemented here as
    amount_zscore_for_method: how many standard deviations this amount is
    from the recent mean for payments of the SAME method (card vs upi vs
    netbanking have very different normal amount ranges, so comparing
    across methods would just be noise).
  - PaySim's `type` signal (fraud concentrated in TRANSFER/CASH_OUT) has
    only a loose analog in Razorpay's `method` field, and there's no
    labeled real-world data available to this project to calibrate
    per-method fraud rates against — deliberately NOT hardcoded as a rule
    here; that's a Day 5 scoping call, not a Day 4 feature.
  - What REPLACES the balance-drain signal: velocity and identity checks —
    txns_last_1h_same_email, txns_last_24h_same_card, is_new_email. This
    is the standard substitute in real payment-gateway fraud detection
    when account-balance data isn't available — rapid repeated attempts
    from the same email/card, or a brand-new identity attempting a
    payment, are arguably MORE relevant to gateway-level fraud (card
    testing sprees, stolen-card runs) than balance drainage is anyway.

Pure functions here take plain lists of dicts shaped like a sql/schema.sql
transactions row, so they're testable without a live database connection —
same "keep the core logic testable in isolation" pattern already used for
webhook_verify.py (split out of webhook_listener.py) and agent_tools.py's
tool_* functions (split from the eventual Agent SDK wiring).
"""

import statistics
from typing import Optional


def _same_card_key(txn: dict) -> Optional[tuple]:
    """card_last4 + card_network together, used as a stand-in for "same
    physical card." Not perfect — Razorpay's card_id can change per
    tokenization even for the same physical card in some flows — but
    last4+network is the best identity signal actually present in
    schema.sql's columns, and is the same imperfect proxy real payment
    gateways commonly fall back on."""
    if txn.get("method") != "card":
        return None
    last4 = txn.get("card_last4")
    network = txn.get("card_network")
    if not last4 or not network:
        return None
    return (last4, network)


def compute_features(new_txn: dict, prior_txns: list) -> dict:
    """
    new_txn: dict shaped like a sql/schema.sql transactions row for the
        transaction being scored right now — must have 'email', 'method',
        'amount', 'razorpay_created_at', and (if method == 'card')
        'card_last4' / 'card_network'.
    prior_txns: list of dicts, same shape, for transactions seen BEFORE
        new_txn (any status). Must NOT include new_txn itself.

    Returns a dict with exactly the four schema.sql feature columns.
    """
    now = new_txn["razorpay_created_at"]
    email = new_txn.get("email")
    method = new_txn.get("method")
    amount = new_txn.get("amount")

    # --- txns_last_1h_same_email ---
    txns_last_1h_same_email = 0
    if email:
        txns_last_1h_same_email = sum(
            1
            for t in prior_txns
            if t.get("email") == email and now - 3600 <= t["razorpay_created_at"] < now
        )

    # --- is_new_email ---
    is_new_email = 1 if email and not any(t.get("email") == email for t in prior_txns) else 0

    # --- txns_last_24h_same_card ---
    txns_last_24h_same_card = 0
    card_key = _same_card_key(new_txn)
    if card_key is not None:
        txns_last_24h_same_card = sum(
            1
            for t in prior_txns
            if _same_card_key(t) == card_key and now - 86400 <= t["razorpay_created_at"] < now
        )

    # --- amount_zscore_for_method ---
    # Cold-start problem, stated plainly rather than hidden: with fewer than
    # 2 prior same-method transactions there's no meaningful distribution to
    # compare against, so this returns None (NULL in the DB) rather than a
    # fabricated 0.0 — a 0.0 would falsely claim "perfectly average," which
    # this function has no basis to claim yet.
    same_method_amounts = [
        t["amount"] for t in prior_txns if t.get("method") == method and "amount" in t
    ]
    if len(same_method_amounts) >= 2:
        mean = statistics.mean(same_method_amounts)
        stdev = statistics.stdev(same_method_amounts)
        amount_zscore_for_method = (amount - mean) / stdev if stdev > 0 else 0.0
    else:
        amount_zscore_for_method = None

    return {
        "txns_last_1h_same_email": txns_last_1h_same_email,
        "txns_last_24h_same_card": txns_last_24h_same_card,
        "is_new_email": is_new_email,
        "amount_zscore_for_method": amount_zscore_for_method,
    }


def compute_features_from_db(conn, new_txn: dict) -> dict:
    """
    Thin I/O wrapper: pulls the relevant prior rows out of a real
    sql/schema.sql `transactions` table (an already-open sqlite3
    connection) and calls the pure compute_features() above. Kept separate
    so the actual feature LOGIC stays testable without a database — same
    split as webhook_verify.py out of webhook_listener.py.
    """
    cursor = conn.execute(
        "SELECT email, method, amount, card_last4, card_network, razorpay_created_at "
        "FROM transactions WHERE payment_id != ?",
        (new_txn.get("payment_id", ""),),
    )
    columns = [d[0] for d in cursor.description]
    prior_txns = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return compute_features(new_txn, prior_txns)
