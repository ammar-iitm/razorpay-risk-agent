"""
day5/rule_engine.py — the rule-based fraud detector, evaluated against
PaySim's labeled data to produce the precision/recall metrics the
buildathon track explicitly asks for.

Scope note, worth being explicit about: this scores PaySim's OWN columns
(type, oldbalanceOrg/newbalanceOrig, amount), because PaySim is the only
data this project has with a real fraud label (isFraud) to evaluate
against — Razorpay's test mode has none (see docs/ARCHITECTURE.md §6).
This is deliberately a DIFFERENT function from day4/feature_engineering.py,
which computes Razorpay-native features (velocity/identity/z-score) for the
live agent path — the two domains don't share columns, so they can't share
a scoring function. What they DO share is the same rule STRUCTURE: a small
number of independently-explainable signals, weighted and summed, rather
than one opaque black-box score. That structure is the thing Day 5's
evaluation actually validates, and it's the same structure Day 6/7 will
reuse (with Razorpay-native inputs) once live scoring is wired up.

Weights below are not arbitrary — they trace directly to day3/FINDINGS.md's
real numbers from the actual dataset:
  - origin_drained_to_zero alone had ~97.5% recall (FINDINGS.md Signal 2) —
    the single strongest lever found, so it gets the largest weight.
  - transaction type was a clean zero-fraud filter for 56% of the dataset
    (FINDINGS.md Signal 1) — real, but secondary — moderate weight.
  - amount ran ~8x higher on average for fraud (FINDINGS.md Signal 3), but
    with heavy overlap at the tails (fraud min was ₹0, legit max was
    ₹92.4M) — real, but noisiest — smallest weight, kept continuous rather
    than a hard cutoff.
"""

RISKY_TYPES = {"TRANSFER", "CASH_OUT"}

WEIGHT_TYPE = 0.3
WEIGHT_DRAIN = 0.5
WEIGHT_AMOUNT = 0.2


def rule_score(row: dict, amount_scale: float) -> tuple:
    """
    row: dict with PaySim's own column names — 'type', 'amount',
        'oldbalanceOrg', 'newbalanceOrig'.
    amount_scale: a reference amount (e.g. a high percentile of `amount`
        computed from the training data) used to scale the amount
        component into [0, 1]. Passed in rather than hardcoded so this
        function stays testable and the scale comes from real data chosen
        by the caller, not guessed here.

    Returns (score, reason_codes): score in [0, 1] (sum of the three
    weights, so 1.0 only when every signal fires at its max), and
    reason_codes — which signals fired, mirroring risk_scores.reason_codes
    in sql/schema.sql.
    """
    if amount_scale <= 0:
        raise ValueError("amount_scale must be > 0")

    score = 0.0
    reasons = []

    if row.get("type") in RISKY_TYPES:
        score += WEIGHT_TYPE
        reasons.append("risky_type")

    origin_drained = row.get("oldbalanceOrg", 0) > 0 and row.get("newbalanceOrig", 0) == 0
    if origin_drained:
        score += WEIGHT_DRAIN
        reasons.append("origin_drained")

    amount_component = min(row.get("amount", 0) / amount_scale, 1.0) * WEIGHT_AMOUNT
    score += amount_component
    if amount_component >= WEIGHT_AMOUNT * 0.5:
        reasons.append("amount_elevated")

    return score, reasons
