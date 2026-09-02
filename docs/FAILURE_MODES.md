# Failure modes: what broke, and what's deliberately out of scope

The buildathon's own submission form asks for real technical failures and
how they were recovered from — this doc is a curated answer, pulled from
[`docs/BUILD_LOG.md`](BUILD_LOG.md)'s full day-by-day account. Everything
below actually happened during this build; nothing here is a hypothetical
"what could go wrong" exercise. Each entry links to the build-log section
with the full trace (commands run, exact error text, verification steps)
for anyone who wants to check the claim rather than take it on faith.

Two categories, on purpose: bugs that got **fixed**, and limitations that
are **documented and left as-is** because fixing them would mean building
a feature this 10-day solo build never claimed to have. Mixing the two
together — or worse, only showing the fixes — would misrepresent what's
actually been verified.

## Real bugs found and fixed

**A malformed webhook body could retry forever.** Razorpay's webhook
signature only proves the sender knew the secret — it says nothing about
whether the body is valid JSON. An unhandled `json.loads()` on a body that
didn't parse threw a raw `500` with a full traceback, and because
Razorpay's real webhook delivery retries on any non-2xx response, one bad
payload would have retried indefinitely instead of failing once and
staying failed. Found by sending a body that doesn't parse, signed
correctly over those exact bytes, through the actual Flask route. Fixed
with a `try/except` around the parse, returning a clean `400`; re-verified
the signature check still runs first and rejects a wrong signature exactly
as before. (Day 10)

**Six tool functions crashed on a well-formed but unknown id.** Every
`tool_*` function that logs to the audit trail (`hold_payment`,
`release_payment`, `notify_merchant`, `draft_dispute_evidence`,
`submit_dispute_evidence`, `accept_dispute`) unconditionally wrote to
`agent_actions`, whose `payment_id`/`dispute_id` columns are real foreign
keys into `transactions`/`disputes`. Handing any of them an id that looked
valid (`pay_...`/`disp_...`) but was never actually inserted crashed with
`sqlite3.IntegrityError: FOREIGN KEY constraint failed` — reachable both
from a hallucinated-but-well-formed id from the live agent (the existing
permission gate only checks the id's *shape*, not that it exists) and from
any direct call bypassing that gate entirely (three of this repo's own
scripts do). Found while testing a "missing data" scenario for the agent
tools, not by inspection. Fixed with one shared check applied consistently
across all six functions: look the id up first, and if it's not there,
return a clean `not_found` result before any live Razorpay call, policy
evaluation, or log write happens — deliberately not logged to the audit
trail either, since a foreign key can't reference a row that doesn't
exist, and an unknown id is an input-validation failure, not a real
decision about real data. Verified all six independently, confirmed zero
audit-log pollution, and re-ran the full demo scenario to confirm nothing
about the normal path changed. (Day 10)

**A schema repair silently zeroed a column instead of asking what really
happened.** A `risk_agent.db` created before Day 7 added the `on_hold`
column crashed the dashboard's live feed outright (`sqlite3.OperationalError:
no such column: on_hold`) the first time it ran outside the sandbox. The
first fix stopped the crash but its only remedy was a full db wipe — which
would have deleted real historical audit-log entries from an earlier live
agent run, discovered only because real screenshots showed genuine
Claude-generated reasoning text already sitting in that file. The second
fix repaired the schema in place (`ALTER TABLE ... ADD COLUMN`) instead of
wiping it, but `ADD COLUMN ... DEFAULT 0` still silently zeroed `on_hold`
for every pre-existing row — including one that `agent_actions` already
recorded as genuinely held. The audit trail is this project's own source
of truth; the fix should have deferred to it. Fixed a third time with a
function that recomputes `on_hold`/`held_at` directly from each payment's
own `agent_actions` history rather than trusting a column default.
Three passes on one bug, each only caught by checking real data against
the previous fix rather than assuming it was correct because it stopped
the crash. (Day 9)

**A signed webhook body that's valid JSON but not a JSON object crashed
the route.** `[1,2,3]`, a bare number, a bare string, and `null` all
parse cleanly under `json.loads()`, so they sailed past the malformed-JSON
fix above — then `payload.get("event")` threw `AttributeError` because
none of those types have a `.get()` method. A body of genuine binary
garbage crashed differently again: `json.loads()` tries to auto-detect a
text encoding before it parses, and raised `UnicodeDecodeError`, not
`JSONDecodeError`, on bytes that aren't valid text at all — a second
exception type the original `except` clause didn't catch. Found by
throwing a battery of signed-but-hostile bodies at the real `/webhook`
route through Flask's test client, split out specifically because a
correct signature doesn't come with any guarantee about what shape the
underlying JSON takes. Fixed by widening the except clause to catch both
exception types and adding an explicit `isinstance(payload, dict)` check
after parsing — both paths now return a clean `400` instead of a `500`,
preserving the same "don't make Razorpay retry forever" reasoning as the
first webhook fix. (Day 10, edge-case sweep)

**Two dashboard buttons, always visible, chained into two crashes on a
completely fresh page.** `/audit`'s "Tamper row 1" and the live feed's
"Sync hold state from audit log" both render unconditionally, with no
"seed data first" gate. Clicking "Sync hold state" before ever seeding
crashed with `no such table: transactions` — `repair_schema()` assumed a
`transactions` table already existed and just needed a column, but
`sqlite3.connect()`'s own side effect (creating an empty file just by
connecting to a path that doesn't exist) meant one crashed click left a
stray, tableless db file on disk. Because every other route in the app
uses `os.path.exists(DB_PATH)` as its signal for "real data is here,"
that stray file made the next request lie: clicking "Tamper row 1" next
passed the existence check and then crashed on `no such table:
agent_actions`. Reproduced the exact two-click sequence against a fresh
scratch db through Flask's test client before fixing anything. Fixed
`/repair` to initialize a fresh, correctly-shaped db when none exists
instead of attempting an `ALTER TABLE` with nothing to alter, and fixed
`/tamper` to check `sqlite_master` for the table it actually needs
rather than trusting file-existence as a stand-in. Re-ran the identical
click sequence plus a full normal-flow regression (seed, view, tamper,
verify-broken, repair-as-no-op, metrics) against the fix — clean
throughout. (Day 10, edge-case sweep)

**Two connections racing to write the audit log could make an untampered
chain report itself as tampered.** `log_agent_action()` read the current
"last hash" with a plain `SELECT`, then inserted and committed — a
`SELECT` never blocks a writer in SQLite's default rollback-journal mode,
so two connections writing at nearly the same time (e.g. the dashboard and
a live agent run hitting the same `risk_agent.db`) could both read the
same last hash before either committed. The second writer's `this_hash`
then got computed from a `prev_hash` that was already stale by the time
its row actually landed at the next `id`, and `verify_audit_chain()` —
which recomputes hashes strictly in `id` order — reported that mismatch as
tampering that never happened, a false positive against this project's own
core tamper-evidence claim. Found with real threads, not a manual
simulation or code reading: 12 threads racing `log_agent_action()` against
the same payment broke the chain in 5/5 trials before the fix. Fixed by
wrapping the read-then-insert in one `BEGIN IMMEDIATE` transaction, so a
second writer's own `BEGIN IMMEDIATE` blocks (SQLite's busy handler
auto-retries for `connect()`'s 5-second default timeout) until the first
commits and it can see the real last hash. Re-ran the same 12-thread race
20 times after the fix — chain intact every time, 0/20 — and re-verified
every other suite (all three day10 suites, `--demo`, and the live
dashboard's real seed/tamper/audit flow through a running server) still
behaves identically. (Day 10, concurrency pass)

**A stretch-goal file was built under the wrong day.** The Day 5 ML
classifier was initially written and named as if it were Day 8 work,
contradicting the actual build plan. Caught directly, not by me — fixed by
moving the file, correcting every doc and `.gitignore` reference, and
deleting the stale location from both the sandbox and the real repo.
Included here because "the plan said X, the code did Y" is its own failure
mode worth naming, distinct from a runtime bug. (Day 5/8 correction)

**A result too good to trust got checked before it got reported.** The
Day 5 stretch classifier's precision jumped from the rule engine's 4.45%
to 92.97% — a jump large enough to be a documented dataset-leakage
artifact (PaySim's balance columns are a known issue) rather than a real
result. Rather than reporting the headline number, ran a 3-way feature
ablation first; it ruled out leakage (the destination-only feature set
scored *worse* than the rule engine, which leakage wouldn't predict) and
confirmed the gain was real. Not a bug — included because "verify a
suspiciously good number before trusting it" is exactly the kind of
technical judgment this section is meant to demonstrate, not just bug
fixes. (Day 5, continued)

## Known limitations — documented, not fixed, and why

**No live webhook-to-database ingestion pipeline.**
`day2/webhook_listener.py` verifies a Razorpay webhook's signature and
prints the payload; it never writes to `transactions`. Every transaction
in this system today comes from a seed script, each of which resets the
database first. Building a real ingestion path safely means making the
insert idempotent against Razorpay's own webhook retries — real future
work, not a small patch. One direct consequence: duplicate-`payment_id`
handling was tested against the schema directly (a real `INSERT` against
an existing `payment_id` throws `sqlite3.IntegrityError: UNIQUE constraint
failed`) rather than fixed, since there's no live path that could trigger
it today, and "fixing" it would mean building the feature above first.

**No live test of `submit_dispute_evidence` / `accept_dispute` against a
real Razorpay dispute.** Razorpay's test mode has no way to simulate a
dispute — checked directly in the dashboard, not assumed. Both tools are
real, gated API-calling code, verified via a seeded-data live agent run
and unit tests, but never against an actual live Razorpay dispute, because
one only exists when a real cardholder disputes a real charge.
`draft_dispute_evidence` is the exception and is fully live (Day 8) since
drafting only needs the local record, not Razorpay's dispute API.

**`hold_payment` is internal state, not a native Razorpay primitive.**
Razorpay has no "freeze this payment" endpoint. Day 7 made the read side
live (checking real payment status before acting), but the hold itself is
this system's own state layered on top — stated in the architecture, not
hidden behind the word "hold."

**No SHAP/per-feature attribution, no external audit-chain anchoring, no
multi-agent architecture.** All three are real, deliberate scope cuts for
a 10-day solo build, not oversights — reasoning for each in
`ARCHITECTURE.md` §7, §8, and the roadmap in §11.

## Why this list looks the way it does

Every fixed bug above was found by actually running the code against a
real or realistic input — a hand-built stale database, a deliberately
malformed webhook body, a hallucinated-but-well-formed id — not by
reasoning about what might go wrong. Every documented limitation was
checked directly (the dispute-simulation gap by looking in the actual
Razorpay dashboard; the duplicate-id question by throwing a real duplicate
`INSERT` at the real schema) rather than asserted. That distinction is the
point of this document: a repo that shows its failures, and shows they
were actually tested rather than assumed, is more credible than one that
claims to have none.
