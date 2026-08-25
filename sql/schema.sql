-- ============================================================================
-- Razorpay AI Risk Manager — Data Model
-- SQLite-compatible DDL (swap AUTOINCREMENT/TEXT types for Postgres if needed)
--
-- Design intent: every table here exists to answer one of the judges' three
-- questions —
--   1. "Why did the agent do that?"        -> risk_scores + agent_actions
--   2. "Can I trust the audit trail?"       -> agent_actions hash chain
--   3. "Was this bounded, not free-range?"  -> policy_config + agent_actions.decision_tier
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. transactions
-- Mirrors the fields we actually get back from Razorpay's Orders + Payments
-- APIs (see docs/API_NOTES.md for the exact source fields). This is the raw
-- fact table — nothing here is inferred, everything is inferred is the
-- risk_scores stage.
-- ----------------------------------------------------------------------------
CREATE TABLE transactions (
    payment_id          TEXT PRIMARY KEY,          -- Razorpay payment id, e.g. "pay_L0nSsccovt6zyp"
    order_id             TEXT,                       -- Razorpay order id, e.g. "order_RB58MiP5SPFYyM"
    amount               INTEGER NOT NULL,           -- amount in paise (INR subunits) — never store as float
    currency             TEXT NOT NULL DEFAULT 'INR',
    status                TEXT NOT NULL CHECK (status IN ('created','authorized','captured','failed','refunded')),
    method                TEXT,                       -- card | upi | netbanking | wallet | emi
    captured             INTEGER NOT NULL DEFAULT 0, -- boolean 0/1
    email                 TEXT,
    contact               TEXT,
    card_network         TEXT,                       -- Visa | Mastercard | Rupay | ... (null if not card)
    card_last4           TEXT,
    vpa                   TEXT,                       -- UPI virtual payment address, null if not UPI
    bank                  TEXT,                       -- 4-char bank code, null if not netbanking
    error_code            TEXT,                       -- populated only when status = 'failed'
    error_description    TEXT,
    error_reason          TEXT,
    notes                 TEXT,                       -- raw JSON blob of Razorpay `notes` field
    razorpay_created_at  INTEGER NOT NULL,            -- unix ts from Razorpay
    ingested_at           INTEGER NOT NULL DEFAULT (strftime('%s','now')), -- when OUR system first saw it
    -- lightweight fields the risk model actually needs at inference time,
    -- computed on ingest rather than joined at query time (speed + simplicity):
    txns_last_1h_same_email    INTEGER DEFAULT 0,   -- velocity feature
    txns_last_24h_same_card    INTEGER DEFAULT 0,   -- velocity feature
    is_new_email                INTEGER DEFAULT 0,   -- first time we've seen this email
    amount_zscore_for_method   REAL                  -- how anomalous is this amount vs recent same-method txns
);

CREATE INDEX idx_transactions_email ON transactions(email);
CREATE INDEX idx_transactions_created ON transactions(razorpay_created_at);

-- ----------------------------------------------------------------------------
-- 2. risk_scores
-- One row per scoring event. A transaction CAN be rescored (e.g. after a
-- dispute lands), so this is append-only, not upsert-on-transaction.
-- ----------------------------------------------------------------------------
CREATE TABLE risk_scores (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id            TEXT NOT NULL REFERENCES transactions(payment_id),
    score                  REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    model_version          TEXT NOT NULL,             -- e.g. "hybrid-v0.3" — ALWAYS version your model
    reason_codes           TEXT NOT NULL,             -- JSON array, e.g. ["velocity_high","new_email","amount_outlier"]
    feature_snapshot       TEXT NOT NULL,             -- JSON: the exact feature vector used -> reproducibility
    scoring_source         TEXT NOT NULL CHECK (scoring_source IN ('rule_engine','ml_model','hybrid')),
    scored_at              INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX idx_risk_scores_payment ON risk_scores(payment_id);

-- ----------------------------------------------------------------------------
-- 3. agent_actions  — THE AUDIT TRAIL
-- Append-only, hash-chained (prev_hash / this_hash) so tampering is
-- detectable: this_hash = sha256(prev_hash || canonical_json(row minus this_hash)).
-- This is the single table you'll show the panel first.
-- ----------------------------------------------------------------------------
CREATE TABLE agent_actions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id            TEXT REFERENCES transactions(payment_id),
    dispute_id             TEXT REFERENCES disputes(dispute_id),   -- nullable, set for dispute-related actions
    action_type            TEXT NOT NULL CHECK (action_type IN
                              ('hold_payment','release_payment','draft_dispute_evidence',
                               'submit_dispute_evidence','accept_dispute','notify_merchant','no_action')),
    decision_tier           TEXT NOT NULL CHECK (decision_tier IN
                              ('auto_executed','queued_for_approval','denied','human_approved','human_rejected')),
    risk_score_at_decision REAL,
    policy_rule_applied    TEXT NOT NULL,             -- FK-ish reference to policy_config.rule_name
    agent_reasoning        TEXT NOT NULL,              -- Claude's own explanation for the action, verbatim
    tool_input              TEXT NOT NULL,              -- JSON: exact tool call arguments
    tool_output             TEXT,                        -- JSON: exact tool call result
    actor                   TEXT NOT NULL CHECK (actor IN ('agent','human')),
    approved_by              TEXT,                        -- human identifier, set only when decision_tier involves a human
    prev_hash                TEXT NOT NULL,              -- hash of previous row, '0'*64 for the first row
    this_hash                 TEXT NOT NULL,              -- sha256(prev_hash + canonical_json(this row))
    created_at               INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX idx_agent_actions_payment ON agent_actions(payment_id);
CREATE INDEX idx_agent_actions_tier ON agent_actions(decision_tier);

-- ----------------------------------------------------------------------------
-- 4. disputes
-- Mirrors Razorpay's dispute webhook payload fields (payment.dispute.*).
-- ----------------------------------------------------------------------------
CREATE TABLE disputes (
    dispute_id             TEXT PRIMARY KEY,          -- e.g. "disp_xxx"
    payment_id              TEXT NOT NULL REFERENCES transactions(payment_id),
    amount                   INTEGER NOT NULL,
    currency                 TEXT NOT NULL DEFAULT 'INR',
    reason_code              TEXT,                      -- e.g. "processed_invalid_expired_card"
    phase                     TEXT CHECK (phase IN ('chargeback','fraud')),
    status                    TEXT NOT NULL CHECK (status IN ('open','under_review','action_required','won','lost','closed')),
    respond_by                INTEGER,                   -- unix ts deadline — drives your urgency logic
    evidence_draft            TEXT,                       -- JSON: agent-drafted evidence (summary, explanation_letter, etc.)
    evidence_submitted        INTEGER NOT NULL DEFAULT 0,
    razorpay_created_at      INTEGER NOT NULL,
    ingested_at                INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX idx_disputes_payment ON disputes(payment_id);
CREATE INDEX idx_disputes_status ON disputes(status);

-- ----------------------------------------------------------------------------
-- 5. policy_config — THE BOUNDARIES
-- This table IS your "bounded and gated" story. It's versioned so you can
-- show the panel "here's the exact rule that let this action through."
-- Loaded into the agent's can_use_tool permission handler at startup.
-- ----------------------------------------------------------------------------
CREATE TABLE policy_config (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name              TEXT NOT NULL,
    action_type             TEXT NOT NULL,             -- matches agent_actions.action_type
    condition_json           TEXT NOT NULL,              -- JSON logic, e.g. {"risk_score":{">=":0.75}}
    autonomy_tier            TEXT NOT NULL CHECK (autonomy_tier IN ('auto','approval_required','never_auto')),
    version                  INTEGER NOT NULL DEFAULT 1,
    effective_from           INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    is_active                INTEGER NOT NULL DEFAULT 1
);

-- Seed data: thresholds below are evidence-based, not guessed — from Day 5's
-- actual precision/recall evaluation against PaySim (day5/evaluate.py,
-- day5/pick_thresholds.py). risk_score >= 0.8 is where day5/rule_engine.py's
-- score structurally requires "risky type AND origin drained" to both fire
-- (0.3 + 0.5 weights = 0.8 exactly) — recall jumps from 70% to 97.55% right
-- at this threshold, while precision barely changes above it. See
-- docs/ARCHITECTURE.md §4 for the full reasoning, including why there's
-- deliberately no separate higher-score tier.
INSERT INTO policy_config (rule_name, action_type, condition_json, autonomy_tier) VALUES
('low_risk_no_action',        'no_action',               '{"risk_score":{"<":0.8}}',                              'auto'),
('mid_risk_small_amount_hold','hold_payment',             '{"risk_score":{">=":0.8},"amount":{"<=":1000000}}',    'auto'),
('large_amount_hold',         'hold_payment',             '{"amount":{">":1000000}}',                              'approval_required'),
('release_after_review',      'release_payment',          '{"risk_score":{"<":0.8}}',                              'auto'),
('draft_evidence_always',     'draft_dispute_evidence',   '{}',                                                     'auto'),
('submit_evidence_gate',      'submit_dispute_evidence',  '{}',                                                     'approval_required'),
('accept_dispute_gate',       'accept_dispute',           '{}',                                                     'never_auto'),
('notify_merchant_always',    'notify_merchant',          '{}',                                                     'auto');
