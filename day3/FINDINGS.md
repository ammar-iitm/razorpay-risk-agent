# Day 3 findings — PaySim, real run

Numbers from the actual `explore_dataset.py` run against the full PaySim
dataset (6,362,620 rows), not the synthetic stand-in used to test the
script. These are the real inputs Day 5's rule engine should be built and
thresholded against.

## Class imbalance

- Total transactions: 6,362,620
- Fraud: 8,213 (**0.1291%**)
- This is more extreme than assumed during scoping — confirms accuracy is
  meaningless here and precision/recall (per `ARCHITECTURE.md` §6) is the
  only honest way to evaluate a detector.

## Signal 1 — transaction type (cheap first-pass filter)

| type | total_txns | fraud_txns | fraud_rate |
|---|---|---|---|
| TRANSFER | 532,909 | 4,097 | 0.7688% |
| CASH_OUT | 2,237,500 | 4,116 | 0.1840% |
| CASH_IN | 1,399,284 | 0 | 0% |
| DEBIT | 41,432 | 0 | 0% |
| PAYMENT | 2,151,495 | 0 | 0% |

`CASH_IN` + `DEBIT` + `PAYMENT` = 3,592,211 rows (56.5% of the whole
dataset) with **zero** fraud among them in this data. Candidate for the
rule engine's cheapest, first-evaluated condition: only transactions of
type `TRANSFER` or `CASH_OUT` need to go through the rest of the pipeline
at all.

## Signal 2 — origin balance drained to zero (high recall, low precision alone)

| origin_drained_to_zero | total_txns | fraud_rate (= precision if used alone) |
|---|---|---|
| False | 4,842,039 | 0.0042% |
| True | 1,520,581 | 0.5269% |

Doing the recall math from these numbers: the True group alone accounts for
roughly 8,010 of the 8,213 total fraud cases — about **97.5% recall** if
used as a standalone rule. But precision if used standalone is only
~0.53% (1 real fraud case per ~190 flagged) — flags 1.5M legitimate
transactions. **Lesson for Day 5: this is a strong signal to AND together
with type and amount, not a rule to ship on its own.**

## Signal 3 — amount

- Fraud: mean ₹1,467,967, median ₹441,423
- Legit: mean ₹178,197, median ₹74,685
- Fraud amounts run ~8x higher on average. Combinable threshold signal, not
  a clean cutoff on its own (fraud min was ₹0, legit max was ₹92.4M — heavy
  overlap at the tails).

## Working hypothesis for Day 5's first rule

```
flag if:
  type in (TRANSFER, CASH_OUT)
  AND origin_drained_to_zero
  AND amount > <threshold to be tuned against the precision/recall curve>
```

Each condition is independently explainable (maps directly to a
`reason_code` in `agent_tools.py`'s `get_risk_assessment` output) and the
combination is what's expected to lift precision out of the <1% range
without giving up much of that 97.5% recall ceiling. Actual threshold
tuning and the precision/recall curve itself is Day 5's job, not Day 3's —
this file just records the real numbers that decision should be made from.
