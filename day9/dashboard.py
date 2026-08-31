"""
day9/dashboard.py — the browser dashboard (Day 9).

Why Flask: it's the one web framework this project already has proven
dependency on (day2/webhook_listener.py), so this is the "keep the
framework choice boring" call the tracker explicitly asks for — no new
package, no build step, no JS framework, no separate frontend/backend
split to keep in sync during the days left before submission.

Why one file: a judge (or Ammar, mid-panel) should be able to open exactly
one file and see the entire dashboard — routes, queries, and templates
together — rather than hunt across a templates/ folder and three JS files
for a 10-day solo build. Inline render_template_string keeps that true
without sacrificing real Jinja2 templating (conditionals, loops, escaping).

Three routes, matching artifact/tracker.html's Day 9 spec exactly:
  /         Live feed — transactions with risk chips + reason codes
  /audit    Audit trail viewer, chain-verify result shown prominently
  /metrics  PR curve, confusion matrix, Rs cost/value estimate

Every number on /metrics comes from day9/real_results.py, which cites its
sources — nothing on this page is invented for the demo. Every row on /
and /audit is a live SQL query against risk_agent.db — nothing there is a
mock either. The only two POST actions this app exposes (seed / tamper)
are demo controls that call the SAME real functions the CLI --demo and
day6/run_scenario.py use (agent_tools.seed_demo_scenario,
agent_tools.verify_audit_chain) — no dashboard-only shortcut logic that
could drift from what the agent actually does.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import agent_tools  # noqa: E402
import real_results  # noqa: E402

from flask import Flask, redirect, render_template_string, url_for  # noqa: E402

app = Flask(__name__)

BASE_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{{ title }} — Razorpay AI Risk Manager</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #2a2e38; --text: #e6e8ec;
    --muted: #8b92a3; --green: #2ea043; --amber: #d29922; --red: #da3633;
    --accent: #6ea8fe;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }
  nav { display: flex; gap: 4px; padding: 14px 24px; border-bottom: 1px solid var(--border);
        align-items: center; }
  nav a { color: var(--muted); text-decoration: none; padding: 8px 14px; border-radius: 6px;
          font-size: 14px; font-weight: 500; }
  nav a.active { color: var(--text); background: var(--panel); }
  nav .brand-block { display: flex; flex-direction: column; margin-right: 24px; line-height: 1.25; }
  nav .brand { color: var(--text); font-weight: 700; font-size: 15px; }
  nav .brand-sub { color: var(--muted); font-size: 11px; }
  main { max-width: 980px; margin: 0 auto; padding: 28px 24px 60px; }
  h1 { font-size: 20px; margin: 0 0 6px; }
  h2 { font-size: 15px; color: var(--muted); margin: 32px 0 12px; text-transform: uppercase;
       letter-spacing: 0.04em; font-weight: 600; }
  p.sub { color: var(--muted); font-size: 14px; margin: 0 0 20px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
           padding: 18px 20px; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px 10px;
       border-bottom: 1px solid var(--border); }
  td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .chip { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px;
          font-weight: 600; margin: 1px 3px 1px 0; }
  .chip-green { background: rgba(46,160,67,0.18); color: #56d364; }
  .chip-amber { background: rgba(210,153,34,0.18); color: #e3b341; }
  .chip-red { background: rgba(218,54,51,0.18); color: #f85149; }
  .chip-muted { background: rgba(139,146,163,0.15); color: var(--muted); }
  .banner { padding: 14px 18px; border-radius: 8px; font-weight: 600; font-size: 14px;
            display: flex; align-items: center; gap: 10px; }
  .banner-ok { background: rgba(46,160,67,0.14); color: #56d364; border: 1px solid rgba(46,160,67,0.35); }
  .banner-bad { background: rgba(218,54,51,0.14); color: #f85149; border: 1px solid rgba(218,54,51,0.35); }
  code { background: rgba(139,146,163,0.15); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
  .hash { font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted); }
  form.inline { display: inline; }
  button { background: var(--accent); color: #0f1115; border: none; padding: 8px 14px;
           border-radius: 6px; font-weight: 600; font-size: 13px; cursor: pointer; }
  button.danger { background: var(--red); color: white; }
  button.ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .controls { display: flex; gap: 10px; margin: 14px 0 22px; }
  .empty { color: var(--muted); font-size: 14px; padding: 20px 0; text-align: center; }
  .num { font-variant-numeric: tabular-nums; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .stat { font-size: 26px; font-weight: 700; }
  .stat-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
  .note { color: var(--muted); font-size: 12.5px; line-height: 1.5; margin-top: 8px; }
  .bar-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; font-size: 12.5px; }
  .bar-label { width: 230px; flex-shrink: 0; color: var(--muted); }
  .bar-track { flex: 1; background: rgba(139,146,163,0.12); border-radius: 4px; height: 16px; position: relative; }
  .bar-fill { background: var(--accent); border-radius: 4px; height: 100%; }
  .bar-val { width: 60px; text-align: right; flex-shrink: 0; font-variant-numeric: tabular-nums; }
  .chain-strip { display: flex; align-items: center; overflow-x: auto; padding: 4px 2px 10px; }
  .chain-block { flex-shrink: 0; width: 58px; height: 58px; border-radius: 8px; border: 2px solid;
                 display: flex; flex-direction: column; align-items: center; justify-content: center;
                 font-family: ui-monospace, monospace; cursor: default; }
  .chain-block .chain-id { font-size: 10px; color: var(--muted); }
  .chain-block .chain-hash { font-size: 11px; font-weight: 700; margin-top: 2px; }
  .chain-block.ok { background: rgba(46,160,67,0.12); border-color: rgba(46,160,67,0.45); }
  .chain-block.ok .chain-hash { color: #56d364; }
  .chain-block.broken { background: rgba(218,54,51,0.14); border-color: #f85149; }
  .chain-block.broken .chain-hash { color: #f85149; }
  .chain-link { flex-shrink: 0; width: 18px; height: 2px; background: var(--border); }
  .chain-link.broken { background: #f85149; height: 3px; }
</style>
</head>
<body>
<nav>
  <span class="brand-block">
    <span class="brand">Risk Manager</span>
    <span class="brand-sub">Razorpay AI Buildathon &middot; AI Risk Manager track</span>
  </span>
  <a href="{{ url_for('live_feed') }}" class="{{ 'active' if active=='feed' else '' }}">Live feed</a>
  <a href="{{ url_for('audit') }}" class="{{ 'active' if active=='audit' else '' }}">Audit trail</a>
  <a href="{{ url_for('metrics') }}" class="{{ 'active' if active=='metrics' else '' }}">Metrics</a>
</nav>
<main>
{{ body|safe }}
</main>
</body>
</html>
"""


def render(title, active, body):
    return render_template_string(BASE_HTML, title=title, active=active, body=body)


def risk_chip(score):
    if score is None:
        return '<span class="chip chip-muted">unscored</span>'
    cls = "chip-red" if score >= 0.8 else ("chip-amber" if score >= 0.5 else "chip-green")
    return f'<span class="chip {cls}">risk {score:.2f}</span>'


def tier_chip(tier):
    if not tier:
        return '<span class="chip chip-muted">no action yet</span>'
    cls = {"auto_executed": "chip-green", "queued_for_approval": "chip-amber",
           "denied": "chip-red", "human_approved": "chip-green",
           "human_rejected": "chip-red"}.get(tier, "chip-muted")
    return f'<span class="chip {cls}">{tier.replace("_", " ")}</span>'


# ============================================================================
# / — Live feed
# ============================================================================

FEED_BODY = """
<h1>Live transaction feed</h1>
<p class="sub">Every row is a real query against risk_agent.db — latest risk score, reason codes,
hold state, and the most recent policy decision the agent actually logged for that payment.</p>

<div class="controls">
  <form class="inline" method="post" action="{{ url_for('seed') }}">
    <button type="submit">Seed demo data (fresh DB)</button>
  </form>
  <form class="inline" method="post" action="{{ url_for('repair') }}">
    <button type="submit" class="ghost">Sync hold state from audit log</button>
  </form>
  <form class="inline" method="post" action="{{ url_for('reset') }}">
    <button type="submit" class="ghost">Reset (empty DB)</button>
  </form>
</div>
<div class="note">"Sync hold state" recomputes the Hold column from agent_actions (the real record of
what the agent decided) — use it if a row's Hold state ever looks out of step with its Last agent
decision, e.g. after a schema repair on an older db file.</div>

{% if rows %}
<div class="panel">
<div class="grid2">
  <div><div class="stat num">{{ stats.total }}</div><div class="stat-label">Transactions</div></div>
  <div><div class="stat num">{{ stats.on_hold_count }}</div><div class="stat-label">Currently on hold</div></div>
  <div><div class="stat num">Rs {{ "{:,}".format(stats.on_hold_value) }}</div><div class="stat-label">Value on hold</div></div>
  <div><div class="stat num">{{ stats.queued_count }}</div><div class="stat-label">Queued for human review</div></div>
</div>
<div class="note">Every number above is computed from the same rows in the table below — nothing
here is a separate query that could drift from what's actually shown.</div>
</div>

<div class="panel">
<table>
<tr><th>Payment</th><th>Amount</th><th>Status</th><th>Risk</th><th>Reason codes</th><th>Hold</th><th>Last agent decision</th></tr>
{% for r in rows %}
<tr>
  <td><code>{{ r.payment_id }}</code></td>
  <td class="num">Rs {{ "{:,}".format(r.amount // 100) }}</td>
  <td>{{ r.status }}</td>
  <td>{{ risk_chip(r.score)|safe }}</td>
  <td>{% for rc in r.reason_codes %}<span class="chip chip-muted">{{ rc }}</span>{% endfor %}</td>
  <td>{{ "on hold" if r.on_hold else "clear" }}</td>
  <td>{{ tier_chip(r.decision_tier)|safe }}<div class="note">{{ r.policy_rule_applied or "" }}</div></td>
</tr>
{% endfor %}
</table>
</div>
{% else %}
<div class="empty">No transactions yet — click "Seed demo data" to load the scripted scenario
(mid-risk auto-hold, high-risk queued-for-approval, one dispute) through the real agent tools.</div>
{% endif %}
"""

SCHEMA_MISMATCH_BODY = """
<h1>Live transaction feed</h1>
<div class="banner banner-bad">&#9888; risk_agent.db exists on disk but is missing a column this
dashboard expects (<code>{{ missing_col }}</code>). This means it's a file from earlier in the build,
created before that column was added to sql/schema.sql — SQLite doesn't auto-migrate an existing table
when the CREATE TABLE statement changes.</div>
<div class="controls">
  <form class="inline" method="post" action="{{ url_for('repair') }}">
    <button type="submit">Repair schema (adds the missing column, keeps all existing data)</button>
  </form>
  <form class="inline" method="post" action="{{ url_for('reset') }}">
    <button type="submit" class="danger">Full reset (deletes everything, starts from an empty db)</button>
  </form>
</div>
<div class="note">Repair is almost always the right choice — it runs <code>ALTER TABLE ... ADD COLUMN</code>
for exactly what's missing and touches nothing else, so any real transactions, risk scores, or audit-log
history already in this file (e.g. from an earlier live agent run) survives. Reset is destructive and
should only be used if you actually want to start over.</div>
"""

# Every column this dashboard's queries depend on that a later day's
# schema.sql change could plausibly have added to an existing table,
# paired with the exact ALTER TABLE needed to add it without touching any
# other column or existing row. Kept in sync with sql/schema.sql by hand —
# there's no migration framework in a 10-day solo build, so this list is
# deliberately small and explicit rather than a generic schema-diff tool.
_REPAIRABLE_COLUMNS = [
    ("transactions", "on_hold", "ALTER TABLE transactions ADD COLUMN on_hold INTEGER NOT NULL DEFAULT 0"),
    ("transactions", "held_at", "ALTER TABLE transactions ADD COLUMN held_at INTEGER"),
]


def schema_mismatch_column(conn) -> str | None:
    """Returns the name of the first column this dashboard relies on that's
    missing from the live db file, or None if the schema looks current.
    Catches the real failure mode where an old risk_agent.db (created
    before a later day's schema.sql change, e.g. Day 7's on_hold/held_at)
    is still sitting on disk — SQLite tables don't auto-migrate just
    because schema.sql's text changed, so a stale file silently has fewer
    columns than the code expects until something queries the gap."""
    tx_cols = {c[1] for c in conn.execute("PRAGMA table_info(transactions)").fetchall()}
    for required in ("on_hold", "held_at"):
        if required not in tx_cols:
            return f"transactions.{required}"
    return None


def repair_schema(conn) -> list[str]:
    """Adds whatever's missing from _REPAIRABLE_COLUMNS via ALTER TABLE ...
    ADD COLUMN, which SQLite performs in place without touching existing
    rows or any other table — unlike init_db(fresh=True), this can't lose
    real data (e.g. agent_actions rows logged by an earlier live agent
    run). Returns the list of columns actually added.

    ALTER TABLE ... ADD COLUMN on_hold ... DEFAULT 0 sets every EXISTING
    row to 0, regardless of what actually happened to that payment before
    the column existed — for a row whose agent_actions history already
    has a real auto_executed hold_payment logged (e.g. a payment held
    during Day 6/7 testing, before Day 7 added this column), that default
    is simply wrong: the audit trail already records that it WAS held.
    agent_actions is this project's own source of truth (see
    ARCHITECTURE.md's audit trail sections), so immediately after adding
    the column(s), backfill_hold_state() below derives on_hold from that
    log instead of leaving the blanket default in place."""
    existing = {table: {c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for table in {t for t, _, _ in _REPAIRABLE_COLUMNS}}
    added = []
    for table, column, ddl in _REPAIRABLE_COLUMNS:
        if column not in existing[table]:
            conn.execute(ddl)
            added.append(f"{table}.{column}")
    conn.commit()
    if added:
        backfill_hold_state(conn)
    return added


def backfill_hold_state(conn) -> int:
    """Recomputes transactions.on_hold / held_at from agent_actions —
    the real source of truth — for every payment that has at least one
    EXECUTED hold_payment or release_payment action (decision_tier
    'auto_executed' or 'human_approved'; 'queued_for_approval' correctly
    means nothing has actually happened yet, matching tool_hold_payment's
    own logic in agent/agent_tools.py). A payment's current hold state is
    whichever of those two action types was logged most recently. Rows
    with no such history are left untouched. Returns the number of rows
    updated. Idempotent and safe to run any time, not just right after a
    schema repair — it only ever restates what agent_actions already
    says, never invents a new fact."""
    cur = conn.execute(
        """
        UPDATE transactions
        SET on_hold = CASE WHEN (
                SELECT action_type FROM agent_actions
                WHERE payment_id = transactions.payment_id
                  AND action_type IN ('hold_payment','release_payment')
                  AND decision_tier IN ('auto_executed','human_approved')
                ORDER BY id DESC LIMIT 1
            ) = 'hold_payment' THEN 1 ELSE 0 END,
            held_at = CASE WHEN (
                SELECT action_type FROM agent_actions
                WHERE payment_id = transactions.payment_id
                  AND action_type IN ('hold_payment','release_payment')
                  AND decision_tier IN ('auto_executed','human_approved')
                ORDER BY id DESC LIMIT 1
            ) = 'hold_payment' THEN (
                SELECT created_at FROM agent_actions
                WHERE payment_id = transactions.payment_id
                  AND action_type = 'hold_payment'
                  AND decision_tier IN ('auto_executed','human_approved')
                ORDER BY id DESC LIMIT 1
            ) ELSE NULL END
        WHERE EXISTS (
            SELECT 1 FROM agent_actions
            WHERE payment_id = transactions.payment_id
              AND action_type IN ('hold_payment','release_payment')
              AND decision_tier IN ('auto_executed','human_approved')
        )
        """
    )
    conn.commit()
    return cur.rowcount


def feed_stats(rows: list[dict]) -> dict:
    """Every number here is derived from the exact same `rows` the table
    renders, not a second query -- so the stats strip can never show a
    different picture than the table underneath it. Kept as a plain
    function (not inline in the template) so it's testable on its own."""
    on_hold_rows = [r for r in rows if r["on_hold"]]
    return {
        "total": len(rows),
        "on_hold_count": len(on_hold_rows),
        "on_hold_value": sum(r["amount"] for r in on_hold_rows) // 100,  # paise -> Rs
        "queued_count": sum(1 for r in rows if r["decision_tier"] == "queued_for_approval"),
    }


@app.route("/")
def live_feed():
    if not os.path.exists(agent_tools.DB_PATH):
        return render("Live feed", "feed", render_template_string(FEED_BODY, rows=[], stats=feed_stats([]), risk_chip=risk_chip, tier_chip=tier_chip))
    conn = agent_tools.get_conn()
    missing = schema_mismatch_column(conn)
    if missing:
        conn.close()
        return render("Live feed", "feed", render_template_string(SCHEMA_MISMATCH_BODY, missing_col=missing))
    rows = []
    for t in conn.execute("SELECT payment_id, amount, status, on_hold FROM transactions ORDER BY ingested_at DESC").fetchall():
        payment_id, amount, status, on_hold = t
        rs = latest_score_row(conn, payment_id)
        last_action = conn.execute(
            "SELECT decision_tier, policy_rule_applied FROM agent_actions "
            "WHERE payment_id = ? AND action_type IN ('hold_payment','release_payment') "
            "ORDER BY id DESC LIMIT 1", (payment_id,),
        ).fetchone()
        rows.append({
            "payment_id": payment_id, "amount": amount, "status": status, "on_hold": on_hold,
            "score": rs["score"] if rs else None,
            "reason_codes": rs["reason_codes"] if rs else [],
            "decision_tier": last_action[0] if last_action else None,
            "policy_rule_applied": last_action[1] if last_action else None,
        })
    conn.close()
    body = render_template_string(FEED_BODY, rows=rows, stats=feed_stats(rows), risk_chip=risk_chip, tier_chip=tier_chip)
    return render("Live feed", "feed", body)


def latest_score_row(conn, payment_id):
    row = conn.execute(
        "SELECT score, reason_codes FROM risk_scores WHERE payment_id = ? ORDER BY scored_at DESC LIMIT 1",
        (payment_id,),
    ).fetchone()
    if not row:
        return None
    return {"score": row[0], "reason_codes": json.loads(row[1])}


@app.route("/seed", methods=["POST"])
def seed():
    agent_tools.init_db(fresh=True)
    conn = agent_tools.get_conn()
    agent_tools.seed_demo_scenario(conn)
    conn.close()
    return redirect(url_for("live_feed"))


@app.route("/reset", methods=["POST"])
def reset():
    agent_tools.init_db(fresh=True)
    return redirect(url_for("live_feed"))


@app.route("/repair", methods=["POST"])
def repair():
    # Day 10 edge-case pass: "Sync hold state from audit log" is a
    # permanent button in FEED_BODY's controls, visible even on a totally
    # fresh page before "Seed demo data" has ever been clicked — a
    # perfectly reasonable first click for a curious visitor. Before this
    # guard, that click hit sqlite3.connect()'s own side effect (it
    # silently creates an empty file at DB_PATH just by connecting, even
    # though nothing was ever initialized) followed by repair_schema()
    # trying `ALTER TABLE transactions ADD COLUMN ...` against a table
    # that was never created: `sqlite3.OperationalError: no such table:
    # transactions`. Worse, that stray empty file then made every
    # subsequent os.path.exists(DB_PATH) check across this whole app
    # falsely look like "a real db is here" — see the /tamper fix below
    # for the crash that caused downstream. There's nothing to repair
    # when no db exists yet, so this just creates a correctly-shaped
    # empty one instead of attempting an ALTER TABLE with no table to
    # alter.
    if not os.path.exists(agent_tools.DB_PATH):
        agent_tools.init_db(fresh=True)
        return redirect(url_for("live_feed"))
    conn = agent_tools.get_conn()
    repair_schema(conn)  # adds any missing columns; no-op if the schema's already current
    backfill_hold_state(conn)  # always re-derive on_hold/held_at from agent_actions — safe, idempotent,
                                # and is what actually fixes a db that was already repaired once before
                                # this backfill existed (ADD COLUMN's DEFAULT 0 doesn't know better)
    conn.close()
    return redirect(url_for("live_feed"))


# ============================================================================
# /audit — Audit trail viewer
# ============================================================================

AUDIT_BODY = """
<h1>Audit trail</h1>
<p class="sub">agent_actions is append-only and hash-chained: this_hash = sha256(prev_hash + row).
Tamper with any row and every row after it provably breaks — that's what the banner below is checking, live, right now.</p>

{% if intact is not none %}
  {% if intact %}
  <div class="banner banner-ok">&#10003; Chain intact — all {{ row_count }} rows verified, no tampering detected.</div>
  {% else %}
  <div class="banner banner-bad">&#10007; Chain BROKEN at row id {{ bad_row }} — recomputed hash does not match the stored hash. Everything from that row onward is untrusted.</div>
  {% endif %}
{% endif %}

{% if chain_items %}
<div class="chain-strip">
{% for item in chain_items %}
  <div class="chain-block {{ 'broken' if item.row.broken else 'ok' }}" title="row #{{ item.row.id }} — {{ item.row.action_type }}&#10;full hash: {{ item.row.this_hash }}">
    <span class="chain-id">#{{ item.row.id }}</span>
    <span class="chain-hash">{{ item.row.this_hash[:4] }}</span>
  </div>
  {% if not loop.last %}<div class="chain-link {{ 'broken' if item.link_broken else '' }}"></div>{% endif %}
{% endfor %}
</div>
<div class="note">Each block is one <code>agent_actions</code> row, hover for its full hash. Green means its
recomputed hash still matches what's stored; the moment tampering breaks one row, every block from there
onward turns red — that's <code>verify_audit_chain()</code>'s own recomputation, drawn out block by block
instead of just reported as a yes/no.</div>
{% endif %}

<div class="controls">
  <form class="inline" method="post" action="{{ url_for('tamper') }}">
    <button type="submit" class="danger">Tamper row 1 (demo)</button>
  </form>
  <form class="inline" method="post" action="{{ url_for('seed') }}">
    <button type="submit" class="ghost">Reset &amp; reseed (repairs the chain)</button>
  </form>
</div>

{% if rows %}
<div class="panel">
<table>
<tr><th>#</th><th>Action</th><th>Tier</th><th>Rule</th><th>Reasoning</th><th>Hash</th></tr>
{% for r in rows %}
<tr>
  <td class="num">{{ r.id }}</td>
  <td>{{ r.action_type }}</td>
  <td>{{ tier_chip(r.decision_tier)|safe }}</td>
  <td><code>{{ r.policy_rule_applied }}</code></td>
  <td style="max-width:320px">{{ r.agent_reasoning }}</td>
  <td class="hash">{{ r.this_hash[:12] }}&hellip;</td>
</tr>
{% endfor %}
</table>
</div>
{% else %}
<div class="empty">No actions logged yet — seed demo data from the live feed page first.</div>
{% endif %}
"""


def chain_visual_items(rows: list[dict]) -> list[dict]:
    """Builds the block-and-link data the chain-strip template loops over.
    `row.broken` marks every row from the first mismatch onward (matching
    verify_audit_chain()'s own "everything from that row onward is
    untrusted" semantics, not just the single bad row); `link_broken`
    marks the connector INTO the next block, so the link right before the
    first broken block goes red too -- visually, that's exactly where the
    chain actually breaks."""
    items = []
    for i, row in enumerate(rows):
        next_broken = rows[i + 1]["broken"] if i + 1 < len(rows) else False
        items.append({"row": row, "link_broken": next_broken})
    return items


@app.route("/audit")
def audit():
    if not os.path.exists(agent_tools.DB_PATH):
        return render("Audit trail", "audit", render_template_string(
            AUDIT_BODY, rows=[], chain_items=[], intact=None, bad_row=None, row_count=0, tier_chip=tier_chip))
    conn = agent_tools.get_conn()
    intact, bad_row = agent_tools.verify_audit_chain(conn)
    rows = [
        {"id": r[0], "action_type": r[1], "decision_tier": r[2], "policy_rule_applied": r[3], "agent_reasoning": r[4], "this_hash": r[5],
         "broken": bad_row is not None and r[0] >= bad_row}
        for r in conn.execute(
            "SELECT id, action_type, decision_tier, policy_rule_applied, agent_reasoning, this_hash "
            "FROM agent_actions ORDER BY id ASC"
        ).fetchall()
    ]
    conn.close()
    body = render_template_string(
        AUDIT_BODY, rows=rows, chain_items=chain_visual_items(rows),
        intact=intact, bad_row=bad_row, row_count=len(rows), tier_chip=tier_chip,
    )
    return render("Audit trail", "audit", body)


@app.route("/tamper", methods=["POST"])
def tamper():
    # Day 10 edge-case pass: os.path.exists(DB_PATH) alone isn't proof the
    # agent_actions table exists — sqlite3.connect() creates an empty file
    # just by connecting to a path that doesn't exist yet (that's exactly
    # how the /repair bug fixed above left a stray file sitting here
    # before this fix existed), so a file being present doesn't guarantee
    # any table was ever created in it. "Tamper row 1 (demo)" is, like
    # /repair's button, permanently visible on /audit regardless of
    # whether any data has been seeded, so checking the actual table list
    # rather than trusting file existence is the honest guard here.
    if os.path.exists(agent_tools.DB_PATH):
        conn = agent_tools.get_conn()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "agent_actions" in tables:
            conn.execute("UPDATE agent_actions SET agent_reasoning = ? WHERE id = 1", ("TAMPERED — this text was rewritten after the fact",))
            conn.commit()
        conn.close()
    return redirect(url_for("audit"))


# ============================================================================
# /metrics — PR curve, confusion matrix, Rs cost/value estimate
# ============================================================================

METRICS_BODY = """
<h1>Model evaluation</h1>
<p class="sub">Real numbers from real evaluation runs against PaySim (6,362,620 labeled transactions —
Razorpay test mode has no fraud labels to score against, see ARCHITECTURE.md &sect;6).
Full sourcing in day9/real_results.py.</p>

<h2>Rule engine PR curve (what's actually shipped)</h2>
<div class="panel">
{% for p in curve %}
<div class="bar-row">
  <div class="bar-label">{{ p.label }}{{ " (live)" if p.is_shipped else "" }}</div>
  <div class="bar-track"><div class="bar-fill" style="width: {{ (p.recall*100)|round(1) }}%"></div></div>
  <div class="bar-val">{{ (p.recall*100)|round(1) }}% recall</div>
</div>
<div class="note">{{ p.note }}</div>
{% endfor %}
</div>

<h2>Confusion matrix &amp; Rs cost/value &mdash; shipped threshold (0.8)</h2>
<div class="panel">
<div class="grid2">
  <div><div class="stat num">{{ "{:,}".format(shipped.tp) }}</div><div class="stat-label">Fraud caught (TP)</div></div>
  <div><div class="stat num">{{ "{:,}".format(shipped.fp) }}</div><div class="stat-label">Legit held for review (FP)</div></div>
  <div><div class="stat num">{{ "{:,}".format(shipped.fn) }}</div><div class="stat-label">Fraud missed (FN)</div></div>
  <div><div class="stat num">Rs {{ "{:,}".format(shipped.fraud_value_protected_inr) }}</div><div class="stat-label">Fraud value protected</div></div>
</div>
<div class="note">
Rs {{ "{:,}".format(shipped.legit_value_delayed_inr) }} in legitimate payment value gets held for review
alongside it &mdash; a {{ shipped.delayed_to_protected_ratio|round(1) }}&times; ratio of delayed-to-protected value.
That's the real, honest cost of chasing 97.55% recall with a single linear rule: at this precision (0.67%),
almost every hold is a false positive. It's a deliberate choice for a REVIEW gate (holds are reversible,
missed fraud isn't) &mdash; not something to hide behind an accuracy number. Counts are back-calculated from
the saved precision/recall rates and the real fraud count, not a second independent measurement &mdash; see
day9/real_results.py's docstring.
</div>
</div>

<h2>Stretch goal: trained classifier vs. rule engine (benchmark, not deployed)</h2>
<div class="panel">
<table>
<tr><th>Feature set</th><th>Precision (best-F1)</th><th>Recall (best-F1)</th><th>Precision @ recall&ge;90%</th></tr>
{% for row in ablation %}
<tr>
  <td>{{ row.feature_set }}</td>
  <td class="num">{{ (row.precision*100)|round(2) }}%</td>
  <td class="num">{{ (row.recall*100)|round(2) }}%</td>
  <td class="num">{{ (row.precision_at_recall_90*100)|round(2) }}%</td>
</tr>
{% endfor %}
</table>
<div class="note">Evaluated on an identical, temporally held-out test set ({{ "{:,}".format(test_rows) }} rows,
{{ test_fraud }} fraud) &mdash; see ARCHITECTURE.md &sect;3b for the full leakage-ablation methodology
(arXiv:2312.00586) that ruled out PaySim's balance-column leakage before trusting the origin_only/full result.</div>
<div class="note" style="margin-top:10px">{{ not_deployed_note }}</div>
</div>
"""


@app.route("/metrics")
def metrics():
    shipped = real_results.shipped_cost_estimate()
    body = render_template_string(
        METRICS_BODY,
        curve=real_results.RULE_ENGINE_CURVE,
        shipped=shipped,
        ablation=real_results.STRETCH_CLASSIFIER_ABLATION,
        test_rows=real_results.STRETCH_TEST_SET_ROWS,
        test_fraud=real_results.STRETCH_TEST_SET_FRAUD,
        not_deployed_note=real_results.STRETCH_NOT_DEPLOYED_NOTE,
    )
    return render("Metrics", "metrics", body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Dashboard running at http://127.0.0.1:{port} — Ctrl+C to stop.")
    app.run(host="127.0.0.1", port=port, debug=False)
