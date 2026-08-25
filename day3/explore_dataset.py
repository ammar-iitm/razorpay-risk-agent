"""
day3/explore_dataset.py — pandas fundamentals, taught against the real
dataset this project actually needs, not toy data.

Why PaySim and not IEEE-CIS: Razorpay's test mode has no real fraud labels
to learn from (every test payment you make is fake by construction), so Day
3's job is to get a real, labeled fraud dataset onto the machine to build
and evaluate a detector against. PaySim (synthetic mobile-money transfers,
~6.3M rows, 11 columns, one clear `isFraud` label) was chosen over IEEE-CIS
(real e-commerce data, 590k rows but 400+ mostly-anonymized columns) because
it's small enough to learn pandas on today without fighting messy real-world
columns, and its schema (amount, balances before/after, transaction type,
fraud label) maps cleanly onto payment-risk reasoning — which matters more
here than dataset realism, since Day 5's detector is a rule engine, not a
model trained to squeeze out the last percent of accuracy.

Setup (run once, in your terminal — not in this file):
  pip install pandas
  # Get a Kaggle account (free) at kaggle.com if you don't have one.
  # Go to kaggle.com/settings -> API -> "Create New Token" -> downloads kaggle.json
  pip install kaggle
  mkdir -p ~/.kaggle
  mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
  chmod 600 ~/.kaggle/kaggle.json
  kaggle datasets download -d ealaxi/paysim1
  mkdir -p data
  unzip paysim1.zip -d data/
  mv "data/PS_20174392719_1491204439457_log.csv" data/paysim.csv

Run:
  python3 day3/explore_dataset.py

Read the printed output as you go — each section below explains what pandas
operation it's demonstrating and why, right before it runs. This is a
tutorial you execute against real data, not a reference to skim.
"""

import os
import sys

import pandas as pd

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "paysim.csv")


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    if not os.path.exists(DATA_PATH):
        sys.exit(
            f"Dataset not found at {DATA_PATH}\n"
            "Download it first — see the setup instructions in this file's "
            "docstring (top of day3/explore_dataset.py)."
        )

    # ------------------------------------------------------------------
    # 1. Loading data. A DataFrame is pandas' core structure — think of it
    #    as a spreadsheet held in memory: rows, named columns, each column
    #    has its own type. read_csv is the most common way one gets built.
    # ------------------------------------------------------------------
    section("1. Load and get oriented")
    df = pd.read_csv(DATA_PATH)
    print(f"Shape: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print("\nColumn dtypes:")
    print(df.dtypes)
    print("\nFirst 5 rows:")
    print(df.head())

    # ------------------------------------------------------------------
    # 2. Class imbalance. This is THE defining fact about fraud data: the
    #    thing you're trying to catch is rare. value_counts() tabulates how
    #    many rows fall into each distinct value of a column — here, the
    #    isFraud label (0 = legitimate, 1 = fraud).
    # ------------------------------------------------------------------
    section("2. How rare is fraud in this dataset?")
    counts = df["isFraud"].value_counts()
    pct_fraud = counts.get(1, 0) / len(df) * 100
    print(counts)
    print(f"\nFraud is {pct_fraud:.4f}% of all transactions.")
    print(
        "This is why 'accuracy' is a useless metric here — a detector that "
        "NEVER flags anything is still >99% 'accurate'. This is exactly why "
        "the architecture doc scores the detector on precision/recall, not "
        "accuracy."
    )

    # ------------------------------------------------------------------
    # 3. Transaction types and fraud rate per type. groupby() is pandas'
    #    answer to "for each distinct value of column X, compute something
    #    about the other columns" — the same shape of question SQL's GROUP
    #    BY answers. Here: for each transaction `type`, what fraction of
    #    transactions of that type are fraudulent?
    # ------------------------------------------------------------------
    section("3. Fraud rate by transaction type")
    by_type = df.groupby("type")["isFraud"].agg(["count", "sum", "mean"])
    by_type = by_type.rename(
        columns={"count": "total_txns", "sum": "fraud_txns", "mean": "fraud_rate"}
    )
    print(by_type.sort_values("fraud_rate", ascending=False))
    print(
        "\nNotice fraud is concentrated in specific transaction types "
        "(usually TRANSFER and CASH_OUT in this dataset) — that's already a "
        "usable rule-engine signal: transaction type alone is informative "
        "before you even look at amount or balances."
    )

    # ------------------------------------------------------------------
    # 4. Boolean indexing / filtering. df[condition] keeps only rows where
    #    condition is True — the pandas equivalent of a SQL WHERE clause.
    #    Chaining conditions with & (and) / | (or) requires parentheses
    #    around each condition — a very common first-timer trip-up.
    # ------------------------------------------------------------------
    section("4. Filtering: isolate just the fraud rows")
    fraud_only = df[df["isFraud"] == 1]
    legit_only = df[df["isFraud"] == 0]
    print(f"Fraud rows: {len(fraud_only):,}   Legit rows: {len(legit_only):,}")

    # ------------------------------------------------------------------
    # 5. describe() on a numeric column gives count/mean/std/min/quartiles/
    #    max in one call — the fastest way to sanity-check a distribution.
    #    Comparing the same column's describe() output across two filtered
    #    subsets (fraud vs legit) is a core technique for finding signal.
    # ------------------------------------------------------------------
    section("5. Does transaction amount differ between fraud and legit?")
    print("Fraud amount distribution:")
    print(fraud_only["amount"].describe())
    print("\nLegit amount distribution:")
    print(legit_only["amount"].describe())

    # ------------------------------------------------------------------
    # 6. A real, documented PaySim signal: fraud transactions often drain
    #    the origin account to exactly zero. We can check this by building
    #    a new boolean column with a vectorized comparison (no loop needed
    #    — pandas applies the comparison to the whole column at once) and
    #    then reusing groupby() from step 3 to compare fraud rates.
    # ------------------------------------------------------------------
    section("6. A real fraud signal: origin balance drained to zero")
    df["origin_drained_to_zero"] = (df["oldbalanceOrg"] > 0) & (df["newbalanceOrig"] == 0)
    drain_vs_fraud = df.groupby("origin_drained_to_zero")["isFraud"].agg(["count", "mean"])
    drain_vs_fraud = drain_vs_fraud.rename(columns={"count": "total_txns", "mean": "fraud_rate"})
    print(drain_vs_fraud)
    print(
        "\nIf the fraud rate is dramatically higher when origin_drained_to_zero "
        "is True, that's a genuine rule-engine candidate for Day 5 — an "
        "interpretable, explainable signal, not a black-box model output. "
        "This is exactly the kind of feature agent_tools.py's reason_codes "
        "are meant to surface to a human reviewer."
    )

    section("Done")
    print(
        "Next (Day 4): map signals like this one onto real feature columns "
        "in sql/schema.sql's transactions table, using Razorpay's actual "
        "payment fields (not PaySim's) as the live input."
    )


if __name__ == "__main__":
    main()
