"""
day5/pick_thresholds.py — reads the precision/recall curve evaluate.py
already saved and prints the best (highest-precision) threshold available
at several target recall floors. Useful for picking TWO real operating
points, one per policy_config tier (mid-risk 'auto' hold, high-risk
'approval_required'), instead of a single one-size-fits-all cutoff.

Run:
  python3 day5/pick_thresholds.py
"""

import os
import sys

import pandas as pd

CURVE_PATH = os.path.join(os.path.dirname(__file__), "pr_curve_results.csv")
TARGET_RECALLS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99]


def main() -> None:
    if not os.path.exists(CURVE_PATH):
        sys.exit(f"{CURVE_PATH} not found — run day5/evaluate.py first, it saves this file.")

    df = pd.read_csv(CURVE_PATH)
    print(f"{'target_recall':>13} | {'threshold':>10} | {'precision':>10} | {'recall':>8}")
    print("-" * 52)
    for target in TARGET_RECALLS:
        candidates = df[df["recall"] >= target]
        if candidates.empty:
            print(f"{target:>13.2f} | {'—':>10} | {'—':>10} | (no threshold reaches this recall)")
            continue
        best = candidates.loc[candidates["precision"].idxmax()]
        print(f"{target:>13.2f} | {best['threshold']:>10.4f} | {best['precision']:>10.4f} | {best['recall']:>8.4f}")


if __name__ == "__main__":
    main()
