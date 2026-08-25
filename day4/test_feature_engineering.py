"""
day4/test_feature_engineering.py — plain-assertion tests for
feature_engineering.py. No pytest dependency on purpose (same "minimal
dependencies" instinct as webhook_verify.py) — run directly:

  python3 day4/test_feature_engineering.py

Covers the pure compute_features() logic AND the real sqlite-backed
compute_features_from_db() wrapper against the actual sql/schema.sql DDL,
so a passing run means the feature logic is verified against the real
table shape, not just a hand-rolled dict shape that might drift from it.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from feature_engineering import compute_features, compute_features_from_db  # noqa: E402

T = 1_800_000_000  # arbitrary fixed "now", in unix seconds, for reproducible tests
PASSED = 0


def check(label: str, condition: bool) -> None:
    global PASSED
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if condition:
        PASSED += 1
    else:
        raise AssertionError(label)


def main() -> None:
    # ------------------------------------------------------------------
    # is_new_email + txns_last_1h_same_email
    # ------------------------------------------------------------------
    new_txn = {
        "email": "a@x.com",
        "method": "card",
        "amount": 50000,
        "card_last4": "1234",
        "card_network": "Visa",
        "razorpay_created_at": T,
    }
    f = compute_features(new_txn, prior_txns=[])
    check("no prior txns -> is_new_email = 1", f["is_new_email"] == 1)
    check("no prior txns -> txns_last_1h_same_email = 0", f["txns_last_1h_same_email"] == 0)
    check("no prior txns -> amount_zscore is None (cold start)", f["amount_zscore_for_method"] is None)

    prior = [
        {"email": "a@x.com", "method": "card", "amount": 40000, "card_last4": "1234", "card_network": "Visa", "razorpay_created_at": T - 1800},  # 30 min ago — inside 1h window
        {"email": "a@x.com", "method": "card", "amount": 40000, "card_last4": "1234", "card_network": "Visa", "razorpay_created_at": T - 7200},  # 2h ago — outside 1h window
    ]
    f = compute_features(new_txn, prior_txns=prior)
    check("same email seen before -> is_new_email = 0", f["is_new_email"] == 0)
    check("only in-window same-email txn counted", f["txns_last_1h_same_email"] == 1)

    # ------------------------------------------------------------------
    # txns_last_24h_same_card
    # ------------------------------------------------------------------
    prior_cards = [
        {"method": "card", "card_last4": "1234", "card_network": "Visa", "razorpay_created_at": T - 3600, "email": "b@x.com", "amount": 10000},   # 1h ago — inside 24h
        {"method": "card", "card_last4": "1234", "card_network": "Visa", "razorpay_created_at": T - 90000, "email": "b@x.com", "amount": 10000},  # 25h ago — outside 24h
        {"method": "card", "card_last4": "1234", "card_network": "Mastercard", "razorpay_created_at": T - 100, "email": "b@x.com", "amount": 10000},  # same last4, DIFFERENT network — should not match
    ]
    f = compute_features(new_txn, prior_txns=prior_cards)
    check("only same last4+network within 24h counted (not the diff-network one, not the 25h-old one)", f["txns_last_24h_same_card"] == 1)

    non_card_txn = dict(new_txn, method="upi", card_last4=None, card_network=None)
    f = compute_features(non_card_txn, prior_txns=prior_cards)
    check("non-card method -> txns_last_24h_same_card = 0, no crash", f["txns_last_24h_same_card"] == 0)

    # ------------------------------------------------------------------
    # amount_zscore_for_method
    # ------------------------------------------------------------------
    prior_amounts = [
        {"method": "card", "amount": 10000, "email": "c@x.com", "razorpay_created_at": T - 500},
        {"method": "card", "amount": 20000, "email": "c@x.com", "razorpay_created_at": T - 400},
        {"method": "card", "amount": 30000, "email": "c@x.com", "razorpay_created_at": T - 300},
    ]  # mean=20000, sample stdev=10000
    high_amount_txn = dict(new_txn, amount=50000)
    f = compute_features(high_amount_txn, prior_txns=prior_amounts)
    expected_z = (50000 - 20000) / 10000  # = 3.0
    check(f"z-score matches hand-computed value (got {f['amount_zscore_for_method']})", abs(f["amount_zscore_for_method"] - expected_z) < 1e-9)

    identical_amounts = [
        {"method": "card", "amount": 10000, "email": "d@x.com", "razorpay_created_at": T - 500},
        {"method": "card", "amount": 10000, "email": "d@x.com", "razorpay_created_at": T - 400},
    ]  # stdev = 0 — must not divide by zero
    f = compute_features(dict(new_txn, amount=10000), prior_txns=identical_amounts)
    check("zero-stdev case returns 0.0, no ZeroDivisionError", f["amount_zscore_for_method"] == 0.0)

    # ------------------------------------------------------------------
    # compute_features_from_db against the REAL schema.sql DDL
    # ------------------------------------------------------------------
    schema_path = os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")
    with open(schema_path) as fh:
        ddl = fh.read()
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl)

    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, "
        "email, card_last4, card_network, razorpay_created_at) VALUES "
        "('pay_1','order_1',10000,'INR','captured','card',1,'e@x.com','9999','Visa', ?)",
        (T - 1000,),
    )
    conn.execute(
        "INSERT INTO transactions (payment_id, order_id, amount, currency, status, method, captured, "
        "email, card_last4, card_network, razorpay_created_at) VALUES "
        "('pay_2','order_2',12000,'INR','captured','card',1,'e@x.com','9999','Visa', ?)",
        (T - 500,),
    )
    conn.commit()

    new_db_txn = {
        "payment_id": "pay_3",
        "email": "e@x.com",
        "method": "card",
        "amount": 90000,
        "card_last4": "9999",
        "card_network": "Visa",
        "razorpay_created_at": T,
    }
    f = compute_features_from_db(conn, new_db_txn)
    check("DB wrapper: is_new_email correctly False (email seen twice already)", f["is_new_email"] == 0)
    check("DB wrapper: txns_last_1h_same_email = 2 (both prior rows in window)", f["txns_last_1h_same_email"] == 2)
    check("DB wrapper: txns_last_24h_same_card = 2", f["txns_last_24h_same_card"] == 2)
    check("DB wrapper: amount_zscore_for_method computed (not None, 2 prior same-method rows)", f["amount_zscore_for_method"] is not None)
    conn.close()

    print(f"\n{PASSED} checks passed.")


if __name__ == "__main__":
    main()
