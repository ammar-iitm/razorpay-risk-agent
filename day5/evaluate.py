"""
day5/evaluate.py — runs the rule engine against the real PaySim dataset and
produces the precision/recall metrics the buildathon track explicitly asks
for (not a single accuracy number — meaningless on a 0.13%-fraud dataset,
see day3/FINDINGS.md).

Why this file doesn't just call rule_engine.rule_score() row-by-row over
6.3M rows: pandas' per-row .apply() is slow enough at this scale (would run
several minutes) to be a real annoyance during threshold tuning, where
you'll want to re-run this more than once. So this script recomputes the
same logic as a vectorized pandas/numpy operation for speed — BUT it does
not blindly trust that the vectorized version is a faithful copy of the
tested rule_score(). Before trusting the fast path, it draws a random
sample and checks the vectorized scores against rule_score() called
directly, row by row, and refuses to proceed if they disagree. Speed
without giving up the "verified, not assumed" standard the rest of this
project holds to.

Setup:
  pip install scikit-learn
  (pandas already required by day3/explore_dataset.py)

Run:
  python3 day5/evaluate.py                 # full dataset
  python3 day5/evaluate.py --sample 200000  # quick run on a random subset first
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, f1_score

sys.path.insert(0, os.path.dirname(__file__))
from rule_engine import rule_score, RISKY_TYPES, WEIGHT_TYPE, WEIGHT_DRAIN, WEIGHT_AMOUNT  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "paysim.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "pr_curve_results.csv")

CONSISTENCY_CHECK_SAMPLE_SIZE = 1000
AMOUNT_SCALE_PERCENTILE = 0.90


def vectorized_score(df: pd.DataFrame, amount_scale: float) -> np.ndarray:
    """Same logic as rule_engine.rule_score(), rewritten as vectorized
    pandas/numpy operations for speed. Verified against the real
    rule_score() function by check_consistency() before use — see the
    module docstring."""
    risky_type = df["type"].isin(RISKY_TYPES).astype(float)
    origin_drained = ((df["oldbalanceOrg"] > 0) & (df["newbalanceOrig"] == 0)).astype(float)
    amount_component = (df["amount"] / amount_scale).clip(upper=1.0) * WEIGHT_AMOUNT
    return (risky_type * WEIGHT_TYPE + origin_drained * WEIGHT_DRAIN + amount_component).to_numpy()


def check_consistency(df: pd.DataFrame, amount_scale: float, vec_scores: np.ndarray) -> None:
    """Refuses to proceed silently if the fast vectorized path and the
    tested pure function disagree on a random sample — a mismatch here
    means the vectorized rewrite has a bug, and every downstream number
    would be wrong in a way that's easy to miss."""
    n = min(CONSISTENCY_CHECK_SAMPLE_SIZE, len(df))
    sample_idx = np.random.default_rng(42).choice(len(df), size=n, replace=False)
    mismatches = 0
    for i in sample_idx:
        row = df.iloc[i].to_dict()
        expected_score, _ = rule_score(row, amount_scale)
        if abs(expected_score - vec_scores[i]) > 1e-9:
            mismatches += 1
    if mismatches:
        sys.exit(
            f"CONSISTENCY CHECK FAILED: {mismatches}/{n} sampled rows disagree between "
            "the vectorized fast path and the tested rule_score() function. Refusing to "
            "trust the results — this means vectorized_score() has drifted from "
            "rule_engine.rule_score() and needs fixing before evaluating anything."
        )
    print(f"Consistency check passed: {n} randomly sampled rows match rule_score() exactly.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=None, help="Evaluate on a random N-row subset instead of the full dataset (faster, for iterating on thresholds).")
    args = parser.parse_args()

    if not os.path.exists(DATA_PATH):
        sys.exit(f"Dataset not found at {DATA_PATH} — see day3/explore_dataset.py's docstring for download steps.")

    print("Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    if args.sample and args.sample < len(df):
        df = df.sample(n=args.sample, random_state=42).reset_index(drop=True)
        print(f"Using a random sample of {len(df):,} rows.")
    else:
        print(f"Using the full dataset: {len(df):,} rows.")

    amount_scale = float(df["amount"].quantile(AMOUNT_SCALE_PERCENTILE))
    print(f"amount_scale (p{int(AMOUNT_SCALE_PERCENTILE*100)} of amount) = {amount_scale:,.2f}")

    print("Scoring (vectorized)...")
    scores = vectorized_score(df, amount_scale)

    print(f"Verifying against rule_score() on {CONSISTENCY_CHECK_SAMPLE_SIZE} sampled rows...")
    check_consistency(df, amount_scale, scores)

    y_true = df["isFraud"].to_numpy()
    precision, recall, thresholds = precision_recall_curve(y_true, scores)

    # precision/recall arrays are one element longer than thresholds (the
    # last point has no corresponding threshold) — trim to align them.
    precision_t, recall_t = precision[:-1], recall[:-1]

    f1_scores = np.where(
        (precision_t + recall_t) > 0,
        2 * precision_t * recall_t / (precision_t + recall_t),
        0.0,
    )
    best_idx = int(np.argmax(f1_scores))

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total transactions: {len(df):,}   Fraud: {int(y_true.sum()):,} ({y_true.mean()*100:.4f}%)")
    print(f"\nBest-F1 operating point:")
    print(f"  threshold  = {thresholds[best_idx]:.4f}")
    print(f"  precision  = {precision_t[best_idx]:.4f}")
    print(f"  recall     = {recall_t[best_idx]:.4f}")
    print(f"  f1         = {f1_scores[best_idx]:.4f}")

    # A couple of alternate operating points, useful for the "what would
    # you actually ship" conversation — not every use case wants max F1.
    high_recall_idx = np.argmax(recall_t >= 0.90) if (recall_t >= 0.90).any() else None
    if high_recall_idx is not None:
        print(f"\nHighest-precision point with recall >= 0.90:")
        print(f"  threshold  = {thresholds[high_recall_idx]:.4f}")
        print(f"  precision  = {precision_t[high_recall_idx]:.4f}")
        print(f"  recall     = {recall_t[high_recall_idx]:.4f}")

    pd.DataFrame({"threshold": thresholds, "precision": precision_t, "recall": recall_t, "f1": f1_scores}).to_csv(OUT_PATH, index=False)
    print(f"\nFull curve ({len(thresholds):,} points) saved to {OUT_PATH}")
    print("Next: pick an operating point, wire it into sql/schema.sql's policy_config thresholds.")


if __name__ == "__main__":
    main()
