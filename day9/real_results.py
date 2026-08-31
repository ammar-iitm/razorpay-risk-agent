"""
day9/real_results.py — sourced numbers for the /metrics dashboard page.

Every number in this file is either (a) copied verbatim from a real
evaluation already run and documented elsewhere in this repo, with the
source cited in a comment, or (b) explicitly derived from those numbers
with the derivation shown inline. Nothing here is invented for the demo.

Two things this file is NOT:
  1. It is not a live re-scoring of the 6.3M-row PaySim dataset — that
     dataset isn't shipped with the repo (see day3/FINDINGS.md) and
     re-running day5/evaluate.py + day5/stretch_classifier.py from a Flask
     request would take minutes, not be dashboard-interactive. So this is
     baked-in results from real runs, same as any ML product's dashboard
     shows results from a training job, not a live retrain per page load.
  2. The confusion-matrix / cost numbers are NOT exact integer counts —
     the original scripts saved precision/recall percentages, not the raw
     TP/FP/FN/TN counts, so those counts are *back-calculated* from
     precision+recall+known fraud rate, assuming the reported rates hold
     uniformly across the full dataset. That's a real, standard technique
     (you can always recover a confusion matrix from precision, recall, and
     the positive count) but it's an approximation of the ORIGINAL
     evaluation run, not a second independent measurement. Labeled as such
     everywhere it's shown.
"""

from __future__ import annotations

# ============================================================================
# Source: day3/FINDINGS.md (real dataset exploration, PaySim, Day 3)
# ============================================================================
FRAUD_MEAN_AMOUNT_INR = 1_467_967
FRAUD_MEDIAN_AMOUNT_INR = 441_423
LEGIT_MEAN_AMOUNT_INR = 178_197
LEGIT_MEDIAN_AMOUNT_INR = 74_685

# PaySim's real, published totals (6,362,620 rows, 8,213 labeled fraud —
# this is the well-known PaySim dataset size, same file day5/evaluate.py
# and day5/stretch_classifier.py were both run against).
TOTAL_TRANSACTIONS = 6_362_620
TOTAL_FRAUD = 8_213
FRAUD_RATE = TOTAL_FRAUD / TOTAL_TRANSACTIONS  # ~0.129%

# ============================================================================
# Source: docs/ARCHITECTURE.md §4 and §6, README.md "Real results" section,
# sql/schema.sql's policy_config seed comment (Day 5, day5/evaluate.py,
# day5/pick_thresholds.py). This IS the curve wired into policy_config —
# risk_score >= 0.8 is the live "hold_payment" threshold.
# ============================================================================
RULE_ENGINE_CURVE = [
    {
        "label": "shipped threshold (0.8)",
        "threshold": 0.8,
        "precision": 0.0067,
        "recall": 0.9755,
        "is_shipped": True,
        "note": "Where policy_config actually gates hold_payment today. "
                "Recall jumps from 70% to 97.55% right at 0.8 because the "
                "rule engine's weights (0.3 type + 0.5 drain + 0.2 amount) "
                "structurally require 'risky type AND origin drained' to "
                "both fire here.",
    },
    {
        "label": "best-F1 threshold (0.9998)",
        "threshold": 0.9998,
        "precision": 0.0158,
        "recall": 0.5180,
        "is_shipped": False,
        "note": "The precision-maximizing point on the curve — shown for "
                "comparison, NOT what's shipped. Trades most of the recall "
                "away for a still-modest precision gain, which is why 0.8 "
                "was chosen instead: this is a fraud-hold gate, and missing "
                "fraud is treated as more costly than reviewing more "
                "false positives (see ARCHITECTURE.md §4).",
    },
]

# ============================================================================
# Source: docs/ARCHITECTURE.md §3b (Day 5 stretch goal — HistGradientBoosting
# classifier, temporal train/test split, real ablation against PaySim's
# documented balance-column leakage risk, arXiv:2312.00586). This model is
# NOT wired into agent_tools.py's live scoring path — see the "catch" note
# below, surfaced on the dashboard too so it isn't misread as deployed.
# ============================================================================
STRETCH_CLASSIFIER_ABLATION = [
    {"feature_set": "rule_engine (for comparison)", "precision": 0.0445, "recall": 0.5268, "precision_at_recall_90": 0.0175},
    {"feature_set": "ml_model / origin_only", "precision": 0.8490, "recall": 0.9127, "precision_at_recall_90": 0.8568},
    {"feature_set": "ml_model / full (incl. dest balances)", "precision": 0.9297, "recall": 0.8525, "precision_at_recall_90": 0.8493},
    {"feature_set": "ml_model / dest_only", "precision": 0.1287, "recall": 0.0793, "precision_at_recall_90": 0.0050},
]
STRETCH_TEST_SET_ROWS = 1_248_736
STRETCH_TEST_SET_FRAUD = 4_250
STRETCH_NOT_DEPLOYED_NOTE = (
    "This classifier beats the rule engine by a wide margin on the same "
    "held-out test set, and that gain was checked (not just reported) via "
    "a 3-way feature ablation that rules out PaySim's documented "
    "balance-column leakage as the cause. But it is trained entirely on "
    "PaySim-only columns that don't exist in live Razorpay data, and "
    "unlike the rule engine it can't be manually re-derived for "
    "Razorpay-native features — that needs labeled Razorpay fraud "
    "outcomes, which don't exist yet. So this is real, honest proof the "
    "rules-to-ML upgrade path is worth it, not something currently "
    "deciding any real hold. sql/schema.sql already reserves "
    "'ml_model'/'hybrid' in risk_scores.scoring_source for when that "
    "changes. Full derivation: docs/ARCHITECTURE.md §3b."
)


def back_calculated_confusion_matrix(precision: float, recall: float) -> dict:
    """Recover an approximate TP/FP/FN/TN split from precision + recall +
    the known real fraud count, assuming the reported rates hold uniformly
    across the full dataset (the standard way to reconstruct a confusion
    matrix when only the rates were saved, not the raw counts — see this
    module's docstring). NOT a second independent measurement."""
    tp = round(recall * TOTAL_FRAUD)
    predicted_positive = round(tp / precision) if precision > 0 else 0
    fp = max(predicted_positive - tp, 0)
    fn = TOTAL_FRAUD - tp
    tn = TOTAL_TRANSACTIONS - tp - fp - fn
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "predicted_positive": predicted_positive}


def cost_estimate(precision: float, recall: float) -> dict:
    """₹ cost/value estimate for one operating point, built ONLY from real,
    cited numbers: the back-calculated confusion matrix above, and Day 3's
    real fraud/legit mean transaction amounts. Explicit assumption, stated
    plainly rather than hidden: every predicted-positive transaction is
    valued at the FRAUD mean for true positives and the LEGIT mean for
    false positives — i.e. it assumes a caught fraud is worth its average
    amount and a wrongly-held legitimate payment costs its average amount
    in customer friction/delay, not lost value (holds are reviewable, not
    reversed transactions)."""
    cm = back_calculated_confusion_matrix(precision, recall)
    fraud_value_protected = cm["tp"] * FRAUD_MEAN_AMOUNT_INR
    legit_value_delayed = cm["fp"] * LEGIT_MEAN_AMOUNT_INR
    ratio = (legit_value_delayed / fraud_value_protected) if fraud_value_protected else None
    return {
        **cm,
        "fraud_value_protected_inr": fraud_value_protected,
        "legit_value_delayed_inr": legit_value_delayed,
        "delayed_to_protected_ratio": ratio,
    }


def shipped_cost_estimate() -> dict:
    shipped = next(p for p in RULE_ENGINE_CURVE if p["is_shipped"])
    return {**shipped, **cost_estimate(shipped["precision"], shipped["recall"])}


def best_f1_cost_estimate() -> dict:
    bf1 = next(p for p in RULE_ENGINE_CURVE if not p["is_shipped"])
    return {**bf1, **cost_estimate(bf1["precision"], bf1["recall"])}


if __name__ == "__main__":
    import json
    print(json.dumps({
        "shipped": shipped_cost_estimate(),
        "best_f1": best_f1_cost_estimate(),
    }, indent=2))
