"""
day5/test_rule_engine.py — plain-assertion tests for rule_engine.py.
No pytest dependency, same instinct as day4's tests. Run directly:

  python3 day5/test_rule_engine.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rule_engine import rule_score, WEIGHT_TYPE, WEIGHT_DRAIN, WEIGHT_AMOUNT  # noqa: E402

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
    amount_scale = 1000.0

    # No signals fire
    row = {"type": "PAYMENT", "amount": 0, "oldbalanceOrg": 500, "newbalanceOrig": 300}
    score, reasons = rule_score(row, amount_scale)
    check("no signals -> score 0.0", score == 0.0)
    check("no signals -> no reason codes", reasons == [])

    # Only risky type fires
    row = {"type": "TRANSFER", "amount": 0, "oldbalanceOrg": 500, "newbalanceOrig": 300}
    score, reasons = rule_score(row, amount_scale)
    check("type-only -> score == WEIGHT_TYPE", abs(score - WEIGHT_TYPE) < 1e-9)
    check("type-only -> reasons == ['risky_type']", reasons == ["risky_type"])

    # Only drain fires
    row = {"type": "PAYMENT", "amount": 0, "oldbalanceOrg": 500, "newbalanceOrig": 0}
    score, reasons = rule_score(row, amount_scale)
    check("drain-only -> score == WEIGHT_DRAIN", abs(score - WEIGHT_DRAIN) < 1e-9)
    check("drain-only -> reasons == ['origin_drained']", reasons == ["origin_drained"])

    # oldbalanceOrg == 0 should NOT count as "drained" (nothing to drain)
    row = {"type": "PAYMENT", "amount": 0, "oldbalanceOrg": 0, "newbalanceOrig": 0}
    score, reasons = rule_score(row, amount_scale)
    check("zero starting balance is not 'drained' -> no origin_drained reason", "origin_drained" not in reasons)

    # All three fire, amount at/above scale -> capped at exactly 1.0
    row = {"type": "CASH_OUT", "amount": 5000, "oldbalanceOrg": 500, "newbalanceOrig": 0}
    score, reasons = rule_score(row, amount_scale)
    check("all signals + amount >= scale -> score == 1.0 exactly", abs(score - 1.0) < 1e-9)
    check("all three reason codes present", set(reasons) == {"risky_type", "origin_drained", "amount_elevated"})

    # Amount component scales linearly below the cap
    row = {"type": "PAYMENT", "amount": 500, "oldbalanceOrg": 500, "newbalanceOrig": 300}  # amount = half of scale
    score, reasons = rule_score(row, amount_scale)
    expected = 0.5 * WEIGHT_AMOUNT
    check(f"half-scale amount -> amount component == 0.5 * WEIGHT_AMOUNT (got {score})", abs(score - expected) < 1e-9)

    # amount_scale must be positive
    try:
        rule_score({"type": "PAYMENT", "amount": 100, "oldbalanceOrg": 0, "newbalanceOrig": 0}, 0)
        check("amount_scale=0 raises ValueError", False)
    except ValueError:
        check("amount_scale=0 raises ValueError", True)

    print(f"\n{PASSED} checks passed.")


if __name__ == "__main__":
    main()
