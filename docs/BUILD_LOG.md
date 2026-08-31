# Build Log — what broke, and how I fixed it

Kept live, in first person, as it actually happened — not reconstructed
after the fact for the application. This is raw material for the
"explain technical failures and how you recovered" part of the buildathon
submission; trim and polish before pasting in, but the substance here is
real debugging, not a tidied-up story.

---

## Next up (read this first when resuming)

**Status as of 2026-08-26: the Day 5 stretch goal is DONE, verified, and
the decision is made — the model is real, but it does NOT get wired into
the live agent path today.** Full story in the two build log entries below
and `ARCHITECTURE.md` §3b. Short version: a trained classifier beats the
rule engine by a lot (92.97% vs 4.45% best-F1 precision), checked that gain
wasn't PaySim's documented balance-column leakage (it wasn't — an ablation
confirmed it's a real, legitimate result), and confirmed it inherits the
same PaySim-only-columns limitation the rule engine already had (§3a) — so
it's real, honestly-evaluated proof the rules-to-ML upgrade is worth it,
not something that can be deployed against live Razorpay data today (no
labeled Razorpay data exists to train a Razorpay-native version against).

**Status as of 2026-08-26 (later the same day): Day 8 is done and verified
live, end to end, through the actual agent loop.** `tool_draft_dispute_evidence`
now drafts real letters via a live `claude` CLI call, `tool_notify_merchant`
sends real email via SMTP (soft-fails to an honestly-labeled stubbed state
without SMTP configured). Full story in the build log entry below.

**Remaining Day 8 item, not started:** the tracker's own "5-minute admin
task" — pre-filling the static parts of the buildathon application form
(name, college, track, project name) so submission day is lighter. I don't
have the actual form in front of me; this needs you to either paste its
fields or fill it directly when you have Razorpay's application open.

**Status as of 2026-08-26 (later still): Day 9 is done — the browser
dashboard exists, runs, and every route was hit and checked, not just
written.** `day9/dashboard.py` (Flask, reusing the same dependency Day 2
already installed — no new package) with three routes matching the
tracker's spec exactly: `/` (live feed — real transactions, risk chips,
reason codes, hold state, last policy decision), `/audit` (the hash-chain
verify banner, shown live, plus a real tamper-and-repair demo button), and
`/metrics` (rule-engine PR curve, a back-calculated confusion matrix, a
real ₹ cost/value estimate, and the Day 5-stretch ablation table). Every
number on `/metrics` is sourced in `day9/real_results.py`'s comments —
none of it is invented for the demo. Full story in the build log entry
below.

**Next up: Day 10** (`artifact/tracker.html`'s plan — edge cases, failure
modes, README polish, repo cleanup, make the repo public, freeze scope).
After that: the Final Day pitch video, which should lean on `/metrics` and
`/audit` as the visual evidence — a live chain-verify banner and a real PR
curve read better on camera than a terminal log.

**Naming correction, 2026-08-26:** this classifier briefly lived at
`day8/train_classifier.py`. That was a real mistake, not a style choice —
`artifact/tracker.html`'s actual day-by-day plan puts this exact stretch
goal under DAY 5 ("STRETCH, only if the above went faster than planned: fit
a model, compare its PR curve to the rule engine's"), and Day 8 is reserved
for the dispute-evidence-drafting work described above, which hasn't been
started. Caught before it caused real confusion later — moved to
`day5/stretch_classifier.py`, `.gitignore` and this doc updated to match.
See the two build log entries directly below for both the original build
and the correction.

Reminder from setting this plan on 2026-08-25: this was Day 5's deferred
stretch goal ("attempted only after the rule engine ships and is
evaluated," which it has been). Time-boxed to one real day of actual model
work — one baseline, one evaluation pass, one decision, not a tuning
rabbit hole. There's a hard deadline (Sep 5, 2026) and exams on Aug 29-30
already ate into the buffer.

---

## Day 1 — the policy fail-safe caught my own test scenario, not a bug

**What broke:** Ran the demo in `agent_tools.py`, forcing a `hold_payment`
call on a genuinely low-risk transaction (score 0.12), expecting it to
auto-execute. Instead it came back `queued_for_approval`.

**Why:** `policy_config` had no `auto` rule for `hold_payment` at that low a
risk score — the seeded rules only covered mid-risk (0.4–0.75) and high-risk
(≥0.75) cases. A low-risk hold was a combination nothing in the table
defined.

**How I fixed it:** Didn't touch the policy to make the demo "pass." Left it
exactly as-is — `evaluate_policy()`'s default is to fail *safe*
(`approval_required`) for anything with no matching rule, not fail open.
Changed the demo scenario to exercise a case the policy actually defines
(mid-risk, small amount) instead. The fail-safe behavior was correct all
along; my test scenario was the thing that was wrong.

## Planning for Day 5 — admitted a skill gap before it became a build-day failure

**What almost broke:** The original plan assumed training a gradient-boosted
classifier as the baseline fraud detector. I'd never used pandas or sklearn
before — never touched either one.

**How I caught it before it broke anything:** Said so plainly when asked,
instead of assuming I'd pick it up under time pressure on the day itself.
Rescoped Day 5: the rule engine alone (pure pandas filtering, no model
training) is now the P0, evaluated with `sklearn.metrics.precision_recall_curve`
— a handful of lines, not a training pipeline. A classifier became a stretch
goal, attempted only after the rule engine ships and is evaluated.

## Day 2 — Flask import blocked testing the one thing that actually mattered

**What broke:** `webhook_listener.py`'s signature-verification logic
couldn't be tested on my machine, because the whole file imports Flask at
the top and Flask wasn't installed there yet — and the sandboxed dev
environment I was testing in has no internet access, so installing it on
the spot wasn't an option either.

**How I fixed it:** Split the file. `webhook_verify.py` now holds just the
signature check, using only the Python standard library — zero
dependencies. `webhook_listener.py` imports from it. The
security-critical logic is testable anywhere now, Flask installed or not.

## Day 2 — found a `.venv` I didn't trust, and didn't try to debug it

**What I found:** An existing `.venv` in the project folder had none of the
packages I needed, and one entry in its `bin/` folder was named with a
stylized unicode "π" character instead of a normal Python binary name —
not something an ordinary `pip install` produces.

**How I handled it:** Didn't investigate or try to reuse it. Deleted it,
created a fresh one (`python3 -m venv .venv`). Not worth building a
money-adjacent project on top of something I couldn't account for.

**Correction, 2026-08-26:** the same "𝜋thon" symlink turned up again in the
brand-new venv this week — which is the opposite of reassuring on its face,
since recreating the venv was supposed to have gotten rid of whatever this
was. Before assuming the worst, checked it properly this time instead of
just deleting again: it's a real, intentional CPython 3.14 feature, not a
compromise indicator. `venv` module PRs `𝜋thon` as a joke alias alongside
`python`/`python3` (π ≈ 3.14) — see
[cpython#125035](https://github.com/python/cpython/pull/125035) and
[alexwlchan's writeup](https://alexwlchan.net/til/2025/python-3-14/). The
original caution was reasonable given what was known at the time — a
money-adjacent project is exactly where you don't reuse an unexplained
binary — but the root-cause guess was wrong. Worth having both the original
caution AND this correction on record, not just quietly fixing it.

## Day 2 — wrong working directory

**What broke:** `python3 day2/create_test_order.py` failed with
`No such file or directory` — Python was looking for the file relative to
my home folder, not the project folder.

**How I fixed it:** Hadn't actually `cd`'d into the project directory in
that terminal tab. `cd ~/Developer/razorpay-risk-agent`, confirmed with
`pwd`, reran — worked immediately.

## Day 2 — missing `requests` module

**What broke:** `ModuleNotFoundError: No module named 'requests'` on the
first real run of `create_test_order.py`.

**How I fixed it:** Hadn't installed it into the fresh venv yet.
`pip install requests flask` and it ran clean.

## Day 2 — test checkout failed with a generic, unhelpful error

**What broke:** Razorpay's test checkout immediately failed with
"something went wrong, test failed" — no detail, and it looked at first
like it could be a bad key or a bad order.

**Why:** I'd opened `checkout.html` directly as a `file://` URL. Razorpay's
checkout widget talks to a popup window via `postMessage`, and a `file://`
page has a `null` origin in the browser — which silently breaks that
communication. It had nothing to do with the keys or the order at all.

**How I fixed it:** Served the folder over `python3 -m http.server 8000`
and opened it via `http://localhost:8000/...` instead. Fixed immediately.
Left a note directly on the checkout page itself so this doesn't cost
anyone — including me, later — the same debugging time twice.

## Day 2 — chased a dead webhook through three layers before finding the real one

**What broke:** After switching from ngrok to Cloudflare Tunnel (see the earlier
ngrok interstitial entry above), the webhook still never arrived — not even a
failed delivery attempt showed up in Razorpay's own webhook log, despite a real
test payment reaching `status: captured` on Razorpay's side.

**How I ruled things out, in order:**
1. Confirmed the webhook secret was actually loaded into the running listener
   process (env var exported in a different terminal tab than the one that
   started the listener — the process had it empty on a prior run).
2. Confirmed the registered webhook URL matched the live `cloudflared` tunnel
   URL exactly, and that the tunnel process was still up and had registered a
   connection.
3. Confirmed the subscribed events (`payment.captured`, `payment.failed`,
   the dispute events) were correct and the webhook was Active, in Test Mode.
4. Confirmed the actual payment really did reach `captured: true` via
   `fetch_payment.py` — so there was definitely an event for Razorpay to send.
5. Sent a manual `curl -v POST` straight at the tunnel URL to bypass Razorpay
   entirely and isolate tunnel-vs-Razorpay. Got back an HTTP/2 403 — but with
   a valid, unmodified TLS cert for `*.trycloudflare.com` (ruling out a local
   MITM/firewall) and odd `x-apple-*` headers alongside a real `cf-ray`
   header, which first looked like iCloud Private Relay intercepting things.
6. Checked Private Relay directly — already off. Not that.

**The real cause:** Cloudflare applies its own bot-protection layer to the
shared, anonymous `trycloudflare.com` domain that quick tunnels use, and it
flags automated server-to-server POST requests — which is exactly what both
my `curl` test *and* Razorpay's real webhook sender look like — and blocks
them with a 403 before the request ever reaches the tunnel or my local Flask
app. Confirmed against other developers hitting the identical pattern on
Cloudflare's own community forum. Because `trycloudflare.com` is Cloudflare's
shared anonymous domain, not a zone I own, there's no dashboard setting on my
side to allowlist this — same fundamental shape of problem as the ngrok
interstitial, just Cloudflare's version, and just as unfixable from a free
anonymous quick tunnel.

**Fix — confirmed working the next morning:** Switched to Tailscale Funnel
(`brew install tailscale`, `sudo brew services start tailscale` — the
Homebrew formula doesn't auto-start the background daemon on macOS, which
threw its own "failed to connect to local Tailscale service" error the first
time — then `sudo tailscale up` and `sudo tailscale funnel 5000`). Updated
the Razorpay webhook URL to the new `*.ts.net` address, retriggered a test
payment, and got a real signature-verified delivery straight through:
`=== Verified webhook: payment.captured ===` followed by
`POST /webhook HTTP/1.1" 200`. Day 2's webhook piece is fully closed out.

**Side note, not a bug:** the moment the funnel went public, the listener
immediately started getting hit by generic internet-wide vulnerability
scanners probing paths like `/.env`, `/.git/config`, `/wp-json`,
`/actuator/env`, various Jira/Exchange CVE paths, etc. — all correctly
404'd since those routes don't exist. Expected behavior for anything exposed
on the public internet, not specific to this project, but a reminder to run
`sudo tailscale funnel 5000 off` when not actively testing rather than
leaving it open all day.

## Day 2 — two smaller trips along the way

**Port conflict:** `python3 -m http.server 8000` failed with
`OSError: [Errno 48] Address already in use` — a server from an earlier
tab was already serving that port, forgotten about. Didn't need to kill it;
the old one was still serving the same folder fine, so I just reused it via
the existing `http://localhost:8000/day2/checkout.html` instead of starting
a redundant second one.

**Wrong ID type passed to `fetch_payment.py`:** Ran
`python3 day2/fetch_payment.py order_TTk5HTPwZRNCk9` and got a 400 from
Razorpay's API. The script calls `/v1/payments/{id}`, which needs a
`pay_...` payment ID, not an `order_...` order ID — I'd grabbed the wrong
ID out of the terminal history. Fixed by pulling the actual `pay_...` ID
from `checkout.html`'s result box instead.

## Day 5 — the placeholder policy thresholds turned out to be wrong, in a useful way

**What I found:** The original `policy_config` seed data (`mid_risk_small_amount_hold`
at 0.4-0.75, `high_risk_hold` at ≥0.75) was a reasonable-sounding guess made
before any real detector existed. Running `day5/evaluate.py`'s actual
precision/recall curve against PaySim showed the real rule engine's useful
threshold sits at **0.8**, not 0.4 or 0.75 — and it's not arbitrary: 0.8 is
exactly `WEIGHT_TYPE (0.3) + WEIGHT_DRAIN (0.5)`, the point where "risky
type" and "origin drained" both fire together. Recall jumps from 70% to
97.55% right at that threshold and barely improves below it or above it —
precision plateaus around 1.6% across the whole usable range.

**What that meant for the policy:** a second, stricter score-only tier for
`approval_required` wasn't defensible — the score just isn't granular
enough above 0.8 to distinguish "fairly confident" from "very confident."
Removed the separate `high_risk_hold` rule and let amount do that job
instead (`large_amount_hold`, already in the schema, applies regardless of
score — arguably more conservative anyway, since a large transaction
deserves a human's eyes even at a lower confidence flag).

**How I verified the change didn't silently break anything:** `run_demo()`
in `agent_tools.py` had a scripted scenario built around the old 0.4-0.75
placeholder (a 0.55-score transaction expecting `auto_executed`). Updating
the threshold without touching the demo would have silently broken it —
that transaction would've fallen through to the fail-safe
`approval_required` default instead, contradicting the demo's own printed
expectation. Updated the demo's test score to 0.85 and re-ran it end to end
before shipping the change: audit chain intact, tamper detection still
works, both scenarios resolve exactly as printed.

## Day 6 — the orchestrator worked end to end on the first live run

**What I built:** Replaced `run_agent()`'s stub with the real Claude Agent
SDK wiring — all 7 tools exposed, each a thin pass-through to the already-
gated `tool_*` functions so there's exactly one implementation of the
policy logic. Deliberately did NOT duplicate `evaluate_policy()`'s
auto/approval_required decision inside the `can_use_tool` permission
handler — that handler only sees raw tool arguments, not the amount/risk-
score context the real decision needs, so reimplementing it there would
create two places that could silently drift apart (the exact bug class
`day5/evaluate.py`'s consistency check exists to prevent elsewhere in this
project). Instead `can_use_tool` does input validation — denies a tool call
outright if `payment_id`/`dispute_id` doesn't look like a real Razorpay id
(`pay_.../disp_...`), a genuinely different and non-redundant check.

**How I verified it, same two-tier pattern as Day 1's `calculator_with_gate.py`:**
an offline check (`verify_handler_offline()`) that calls the permission
handler directly with malformed and well-formed ids, zero API cost — then a
real live run (`day6/run_scenario.py --live`) against seeded data. The live
run actually worked correctly on the first try: Claude called
`get_risk_assessment` on two payments, correctly auto-held the small-amount
one and correctly got the large-amount one queued for human approval
(matching Day 5's evidence-based `large_amount_hold` policy exactly),
drafted — but never submitted — dispute evidence, and sent one merchant
notification that explicitly separated what actually executed from what's
still pending a human. Audit chain stayed intact through all four real,
logged actions. No bugs to report this time — the "thin pass-through,
single source of truth" design from Days 1-5 paid off directly here.

## Day 7 — wiring live Razorpay checks in without breaking the zero-credential path

**What I built:** `tool_hold_payment` / `tool_release_payment` in
`agent_tools.py` had a literal no-op placeholder (`UPDATE transactions SET
status = status`) where live Razorpay verification was supposed to go. Added
`agent/razorpay_client.py` (a thin, deliberately soft-failing wrapper around
`GET /v1/payments/{id}`) and a new `_verify_live_status()` helper both tools
call before acting: it fetches the payment's real current status, syncs it
into the local `transactions.status` if it's drifted, and — this is the part
I want to call out — if the live status is `refunded` or `failed`, the tool
short-circuits straight to `denied` *before* `evaluate_policy()` even runs,
because "is there anything left to hold" is a factual question, not a policy
judgment, and I didn't want to smuggle it into the policy table as a fake
rule. Also added real `on_hold`/`held_at` columns to `transactions`
(deliberately separate from Razorpay's own `status` field — see
`ARCHITECTURE.md` §5 for why) so `hold_payment`'s auto-execution actually
does something now instead of a no-op.

**The thing I was most careful about, and checked rather than assumed:**
this module is imported unconditionally at the top of `agent_tools.py`, and
`agent_tools.py --demo` has to keep working with zero credentials and zero
network — that's the whole point of the demo path, and it's what a judge
running this cold will actually try first. So `razorpay_client.py` never
raises on a missing key; `credentials_configured()` gates every real call,
and anything unavailable returns `None`, which every caller treats as "skip
live verification," not an error. Re-ran `agent_tools.py --demo` with no
`RAZORPAY_KEY_ID`/`SECRET` set at all after wiring this in — output was
byte-identical to the pre-Day-7 version (`held`, `queued_for_approval`, chain
intact, tamper detection still catches row 1). Then checked the DB directly
and confirmed `on_hold`/`held_at` actually got set on the held payment
instead of the old no-op silently doing nothing.

**Built but not yet run against a real live payment as of this entry:**
`day7/verify_live_hold.py` — takes a real `pay_...` id from a completed Day
2 test checkout, fetches it live, seeds a real transaction row from the
actual API response (same field mapping as `day2/fetch_payment.py`, so
there's one definition of "how a payment maps onto our schema," not two),
then calls the real gated tools and prints the live-verification note that
lands in `agent_reasoning`. Tested its failure paths in the sandbox (no
args, malformed id, no credentials configured, and fake-but-valid-shaped
credentials against a nonexistent payment) — all fail cleanly with a clear
message and no traceback, including the case where it genuinely hits
Razorpay's API and gets an auth rejection back. Haven't run it against a
real completed checkout on my own machine yet — that's the next thing to do
with actual test-mode keys.

**Still open:** whether Razorpay's test mode supports simulating a dispute
at all is unconfirmed — checked Razorpay's own API docs, found no
documented "create test dispute" mechanism. Flagged this honestly in
`ARCHITECTURE.md` §10 rather than guessing. If it turns out not to exist,
the dispute-side tools (`draft/submit_dispute_evidence`, `accept_dispute`)
stay verified the way they already are — Day 6's seeded live agent run plus
unit-level checks — and that's a stated limitation, not a gap I'm pretending
isn't there.

## Day 7 — confirmed Razorpay test mode has no dispute simulation

**What I asked you to check:** whether the Razorpay dashboard (Test Mode →
Disputes) has any "create test dispute" or simulate option, since I
couldn't confirm it either way from Razorpay's own API docs.

**What we found:** it doesn't exist. You checked directly and there's no
such option in test mode. This isn't a bug or something to keep digging
for — it's a real constraint of the platform: a dispute only exists when an
actual cardholder disputes an actual charge, and there's no test-mode
shortcut to manufacture one.

**What that means for the build:** `draft_dispute_evidence`,
`submit_dispute_evidence`, and `accept_dispute` were always going to hit a
ceiling on how "live" they could be verified, and now that ceiling is
confirmed rather than assumed. They stay verified the way Day 6 already
proved them — a real live Claude agent, using the real gated tools, making
the correct call on seeded dispute data (drafting evidence, and correctly
NOT auto-submitting it without human approval) — plus the unit-level checks
underneath. Updated `ARCHITECTURE.md` §10 to state this as a confirmed
platform limitation instead of an open question. Not treating this as
something to route around with a fake dispute row dressed up as "live" —
that would be less honest than just saying what was and wasn't checked
against the real API, which is the whole point of this section existing.

## Day 7 — first live run against a real payment, and a second fail-safe catch

**What happened:** Ran `day7/verify_live_hold.py` against a real completed
Razorpay test-mode checkout (₹499, card, `status=captured`). The hold worked
exactly as designed — live status fetched (`captured`), policy evaluated,
auto-held, `on_hold=1` and a real `held_at` timestamp written, all against
genuine API data for the first time rather than seeded rows. Then called
`tool_release_payment` on the same payment expecting `released`, and got
`queued_for_approval` instead, with `on_hold` still `1`.

**Why, and why it's not a bug:** the script seeds a 0.85 test risk score
specifically to land the hold in the `auto` tier. That same score also
feeds `release_payment`'s policy check — and `policy_config`'s
`release_after_review` rule only auto-releases below a 0.8 score.
0.85 doesn't clear that bar, so `evaluate_policy()` correctly finds no
matching `auto` rule and fails safe to `approval_required`, exactly the
same fail-safe path documented in the very first Day 1 entry of this log —
except this time it triggered on a real live payment instead of a
synthetic scenario I built to prove the mechanism worked.

**Why I'm treating this as a good result, not a loose end:** a payment that
got auto-held because it looked high-risk should NOT be releasable by the
same automated pass that flagged it — that's arguably the correct security
posture, not an accident of test data. Added an inline note to
`verify_live_hold.py` so this reads as intended behavior on future runs
instead of looking like a broken script, rather than "fixing" the test to
avoid hitting the fail-safe.

## Day 5 (continued, 2026-08-26) — built the deferred stretch-goal classifier, found a real (if minor) bug testing it

**What I built:** `day5/stretch_classifier.py` — a `HistGradientBoostingClassifier`
trained on PaySim's raw columns (amount, origin/dest balances, one-hot
transaction type, plus the `origin_drained_to_zero` signal from Day 3),
class-balanced via `sample_weight` since fraud is under 0.2% of rows. Two
methodology decisions I want on record because they're easy to get wrong
silently: split TEMPORALLY by `step` (train on earlier transactions, test
on later ones) rather than randomly, since a trained model — unlike the
hand-authored rule engine — can actually overfit and a random split would
hide that; and re-evaluated the rule engine on this script's own held-out
test set rather than reusing Day 5's full-dataset numbers, so the
model-vs-rule-engine comparison is apples-to-apples on identical rows, not
two different samples.

**What I deliberately did NOT do:** dump the full precision/recall curve to
CSV. Day 5's `pr_curve_results.csv` hit 355MB and blew past GitHub's 100MB
push limit — a mistake fixed reactively that day. This time the script only
ever writes a small summary table (best-F1 point + precision at a handful
of recall floors, ~20 rows total) — designed out of the mistake instead of
just remembering to `.gitignore` it. Also gitignored `day5/model.joblib`
by default (only written with an explicit `--save-model` flag) — a first
exploratory training run shouldn't leave a binary build artifact sitting in
`git status` before anyone's decided it's worth keeping.

**What broke in testing (small, but real):** smoke-testing against
synthetic data threw a `RuntimeWarning: invalid value encountered in
divide` on the F1 calculation for one of the three scorers.
`np.where(cond, a/b, 0.0)` evaluates BOTH branches eagerly in numpy, so a
literal 0/0 division still executes and warns even though `np.where` masks
the result to `0.0` right after — the output was never actually wrong, just
noisy. It didn't show up in Day 5's `evaluate.py`, which has the identical
pattern, purely because that curve (full 6.3M rows) never happened to hit
an exact 0/0 point; this script's smaller, coarser test-set curve did.
Fixed by wrapping the division in `np.errstate(invalid="ignore",
divide="ignore")` — confirmed the actual precision/recall/F1 numbers were
identical before and after the fix, only the spurious warning went away.

**Where this stands:** built and tested end-to-end against synthetic data
in my sandbox — runs clean, `--sample` and `--save-model` both work, output
is sane. Have NOT run it against the real dataset. See "Next up" above.

## Day 5 (continued, 2026-08-26) — the classifier's real numbers were suspicious, so I checked instead of celebrating

**What happened:** ran `day5/stretch_classifier.py` for real against the
full 6.3M-row dataset. Best-F1 precision jumped from the rule engine's
4.45% to 92.97% for the trained model, on the identical held-out test set.
At the recall≥0.90 floor: rule engine 1.75% precision, model 84.93% — a
~48x jump.

**Why I didn't just report that number:** PaySim has a *documented* leakage
problem — a peer-reviewed paper on this exact dataset
([arXiv:2312.00586](https://arxiv.org/html/2312.00586v1)) found the
simulator's balance columns leak the fraud label in a way that's an
artifact of how PaySim generates data, not a real fraud pattern, and
specifically flags the destination-balance columns as needing correction.
The rule engine never used `oldbalanceDest`/`newbalanceDest`; the model
did. A ~48x jump from adding exactly the columns a published paper says are
suspicious is not something to take at face value, on a project where
"verified, not assumed" has been the standard since Day 5's original
consistency check.

**What I did about it:** added a `--feature-set` ablation flag
(`full` / `origin_only` / `dest_only`) and had the real numbers settle it:

- `dest_only` (destination balances alone): 12.87% best-F1 precision, and
  *worse* than the rule engine at recall≥0.90 (0.50% vs. the rule engine's
  1.75%). This rules out the leakage hypothesis in its strong form —
  destination balances alone carry almost no signal here.
- `origin_only` (same information the rule engine has): 84.90% best-F1
  precision, 91.27% recall — nearly matching (and beating on recall) the
  full-feature model's 92.97%/85.25%.

**Real conclusion:** the model's huge win over the rule engine isn't
leakage — it's a gradient-boosted model finding sharper, nonlinear decision
boundaries in the *same information* the rule engine had, instead of one
fixed linear weighted sum. A legitimate, honest result. Decision: if this
model is ever used beyond a benchmark, it trains on `origin_only`, not
`full` — equivalent-to-better performance, and it removes the leakage
question from the conversation entirely instead of needing this ablation
re-explained every time.

**Also tested and rejected:** the naive `hybrid_avg` scorer (a plain
average of the model's probability and the rule engine's score) — it
underperforms the model alone on every single metric in both ablations.
Averaging in a much noisier, weaker score just adds noise; not shipping it.

**The catch, stated plainly rather than glossed over:** this model, exactly
like the rule engine before it (Day 4's honest gap analysis), is trained
entirely on PaySim's own balance columns, which don't exist in live
Razorpay data. Unlike the rule engine, there's no way to manually port this
model's structure to Razorpay-native features the way Day 4 ported the rule
engine's — a trained model needs labeled data, and Razorpay's test mode has
none, which is the whole reason PaySim was substituted in here in the first
place. So this is real, rigorously-verified proof that the rules-to-ML
upgrade path is worth pursuing and exactly how much it's worth — not
something wired into `agent_tools.py`'s live scoring today. Full writeup:
`ARCHITECTURE.md` §3b.

## Day 8 — real dispute drafting and real email, verified through the live agent loop

**What I built:** `tool_draft_dispute_evidence` replaced its deterministic
`[TODO fill]` template with `agent/evidence_drafter.py` — pulls the real
payment/dispute/risk-score rows from the database, builds a prompt that
explicitly forbids inventing supporting facts not in that data, and calls
the authenticated `claude` CLI in print mode (`claude -p "<prompt>"`) for a
single-turn draft. Deliberately NOT the `anthropic` SDK (needs a separate
`ANTHROPIC_API_KEY` — different billing than the Claude subscription this
whole project is built around) and NOT `claude_agent_sdk`'s
`ClaudeSDKClient` (built for multi-turn tool-calling, which a one-shot
letter draft isn't). `tool_notify_merchant` replaced its stub with
`agent/notify_channel.py` — real SMTP email via stdlib `smtplib`, soft-fails
to an honestly-labeled "stubbed" result when `SMTP_*` env vars aren't set.

**What I verified, in order:**
1. Unit-tested `evidence_drafter.py`'s failure paths with mocked
   `subprocess.run` — CLI missing, non-JSON output, timeout, fenced JSON
   extraction, out-of-range confidence clamping. All 5 pass.
2. Unit-tested `notify_channel.py`'s two branches — unconfigured (stub) and
   configured-but-unreachable-host (fails cleanly, doesn't raise). Both pass.
3. Extended `run_demo()` to actually exercise both new tools (it didn't
   before — the module docstring claimed "proves every fallback path
   works" and that would have been false without this). Seeded a real
   demo dispute, ran both tools with zero external config, confirmed
   `--demo` still completes cleanly end to end with the honest fallback
   states (`generated_by=template_fallback`, `sent=False, stubbed`).
4. Ran the real thing against the actual `claude` CLI directly (not through
   `--demo`) — got back a genuinely good, honest letter: thin evidence,
   correctly flagged as thin, confidence self-rated 0.12-0.15 rather than
   an inflated number.
5. Ran `python3 agent/agent_tools.py --demo` again — and it fell back to
   the template on the FIRST attempt despite the CLI being available and
   working (confirmed moments earlier). Re-ran it: succeeded cleanly,
   `generated_by=claude`. This wasn't a bug to chase down — it's the
   soft-fail design doing exactly its job on a real transient hiccup (first
   CLI invocation in a fresh process, plausibly a cold-start/network blip).
   No crash, no silent false claim of success, graceful degradation on the
   bad attempt and a clean real result on the next. Worth having on record
   as an example of the fallback path actually firing on its own, not just
   in a mocked test.
6. Ran the FULL live orchestrator (`day6/run_scenario.py --live`) end to
   end with these new tools wired in through the actual agent loop, not
   direct calls. Claude drafted real evidence (confidence 0.10, correctly
   flagged as weak — no fulfillment proof in the seeded data), and when it
   called `notify_merchant` with no SMTP configured, it read the tool's own
   honest `sent: False` result and told the human, unprompted: *"The
   merchant may not have actually received the email... you should
   configure those environment variables."* That's the soft-fail-and-report
   design working correctly all the way up through the agent's own
   natural-language summary, not just at the tool-return level — a genuine
   payoff of the "never silently claim success" discipline this project has
   held to since Day 7.

**Not done:** the tracker's "5-minute admin task" (pre-filling the
buildathon application form's static fields) — needs the actual form in
front of me or pasted in; see "Next up" above.

---

## Day 9 — the dashboard, and a real reuse-not-duplicate refactor first

Before touching the dashboard itself, `agent/agent_tools.py`'s `run_demo()`
had a problem waiting to happen: it hand-wrote the demo seed data (two
transactions, two risk scores, one dispute) and the three real tool calls
inline, in a function whose whole point is to be a CLI entry point, not a
reusable library call. The tracker's Day 9 spec wants a "seed demo data"
button on the dashboard doing the exact same seeding — and copy-pasting
that block into `day9/dashboard.py` would have created two independent
copies of "what the demo scenario is" that could silently drift apart the
first time either one got edited.

Fixed before writing a single dashboard route: extracted
`seed_demo_scenario(conn) -> dict` out of `run_demo()`'s body. It does the
seeding and the three real tool calls (`tool_hold_payment` twice,
`tool_draft_dispute_evidence`, `tool_notify_merchant`) and returns their
results; `run_demo()` now just calls it and prints from the returned dict.
Deliberately does NOT include `run_demo()`'s tamper-and-reverify trick at
the end — a function meant to be called from a "seed demo data" button
shouldn't leave the audit chain permanently broken as a side effect.
Verified with `python3 -c "import ast; ast.parse(...)"` for syntax, then a
full `rm -f risk_agent.db && python3 agent/agent_tools.py --demo` re-run —
output was byte-for-byte the same shape as before the refactor (mid-risk
auto-hold, high-risk queued, real Claude-drafted evidence at
confidence=0.15, stubbed email, chain intact, then correctly broken after
the CLI's own tamper step). Same "exactly one implementation" discipline
this project has used since Day 1's `evaluate_policy()`.

Then the dashboard itself — `day9/dashboard.py`, Flask (the tracker
explicitly says "keep the framework choice boring," and Flask is already a
proven dependency from Day 2's `webhook_listener.py`; zero new packages).
One file, on purpose — a judge should be able to open exactly one file and
see every route, query, and template together, not hunt across a
`templates/` folder for a 10-day solo build. Three routes, matching the
tracker's spec item for item:

- `/` — live feed. Queries `transactions` joined against each payment's
  latest `risk_scores` row and its most recent `hold_payment`/
  `release_payment` entry in `agent_actions`. Risk chips color by score
  (red ≥0.8, amber ≥0.5, green below), reason codes render as their own
  chips straight from the stored JSON array — nothing summarized or
  reworded. A "Seed demo data" button calls the real
  `seed_demo_scenario()` above (not a dashboard-only copy), and "Reset"
  calls the real `init_db(fresh=True)`.
- `/audit` — calls `verify_audit_chain()` live, on every page load, and
  shows the real result in a banner — green "chain intact" or red "chain
  BROKEN at row id N" — plus the actual `agent_actions` rows with their
  hashes. A "Tamper row 1" button does a real `UPDATE agent_actions SET
  agent_reasoning = ...` and redirects back to `/audit`, so the banner
  visibly flips from green to red on the next load — the same
  tamper-and-reverify proof `--demo` already does at the CLI, now
  click-through. "Reset & reseed" repairs it the same way `--demo`'s own
  fresh run would.
- `/metrics` — the rule engine's real PR curve (both the shipped 0.8
  threshold and the best-F1 point), a back-calculated confusion matrix and
  ₹ cost/value estimate at the shipped threshold, and the full Day
  5-stretch ablation table. Every number here is sourced in
  `day9/real_results.py`'s docstring and comments — the confusion matrix
  is explicitly labeled as back-calculated from precision/recall/fraud-
  count (the original scripts saved rates, not raw counts), and the
  stretch classifier's numbers carry an explicit "not deployed" note so
  the dashboard itself doesn't misrepresent it as live.

Tested for real before delivering, not just written and assumed correct:
started the Flask dev server in the sandbox, then `curl`'d every route —
empty-DB state on `/` (correct "no transactions yet" message), seeded
state (both demo payments with correct risk chips and hold state showing),
`/audit` showing "chain intact" after seeding, tamper flipping it to "chain
BROKEN at row id 1" with the tampered reasoning text visible, reseed
repairing it back to "chain intact," and `/metrics` rendering with no
Jinja errors and the exact ablation numbers from `ARCHITECTURE.md` §3b.
One real hiccup along the way: my first test used `curl -X POST ... -L`,
which showed a confusing `405` — traced it to curl re-issuing the POST
against the redirect target itself (a curl quirk, not a Flask bug); the
server log showed the original `POST /seed` had already returned a correct
`302` and written the data before the spurious follow-up request. Confirmed
by testing without `-L` and checking the server's own access log, not by
assuming it was fine.

---

## Day 9 (continued) — a real crash on the first actual run, on your machine

First time `day9/dashboard.py` was actually run outside the sandbox — on
your machine, against your real `risk_agent.db` — `GET /` threw a 500:
`sqlite3.OperationalError: no such column: on_hold`. This was a real bug in
what I shipped, not a fluke or an environment quirk, and it exposed a gap
in how I'd tested it.

Root cause: `risk_agent.db` in the project root is a persistent file, not
something recreated on every run — it's whatever was last written by any
`dayN` script or the CLI, going back to early in the build, before Day 7
added the `on_hold`/`held_at` columns to `transactions` in `sql/schema.sql`.
SQLite does not migrate an existing table when the `CREATE TABLE` text in
schema.sql changes later — the table on disk keeps whatever columns it had
when it was created, forever, until something explicitly drops and
recreates it. Your local db file predates that column and nothing since
had forced it to be rebuilt, so it sat there silently missing a column
until `dashboard.py`'s live feed was the first thing to actually query it.

The gap in my own testing: I tested the empty-db case (file doesn't exist)
and the freshly-seeded case (file created by `init_db()` from the CURRENT
schema.sql, in the same session), but never a db file that exists and is
simply outdated — the one case that was guaranteed to be true the moment
this ran somewhere other than my sandbox, where I'd never had an old
`risk_agent.db` lying around in the first place. `if not
os.path.exists(DB_PATH)` was checking the wrong thing — "does a file
exist" isn't "is the file's schema what the code expects."

Fixed in `day9/dashboard.py`: added `schema_mismatch_column(conn)`, which
checks (via `PRAGMA table_info`) whether `transactions` actually has the
columns the live feed query needs, before running that query. If it
doesn't, `/` now renders a clear in-page banner explaining exactly why
(leftover file, pre-dates a schema change, SQLite doesn't auto-migrate)
with a working "Reset" button, instead of a raw Flask traceback. Verified
the fix for real, not just written and assumed: built a throwaway sqlite
file by hand with `transactions`/`agent_actions` tables in their
pre-Day-7 shape (no `on_hold`/`held_at`), pointed `RISK_AGENT_DB` at it,
and confirmed through Flask's test client that `GET /` now returns 200
with the banner instead of 500, and that clicking Reset actually recreates
the db from the current schema and the live feed then renders normally.

The honest caveat this doesn't cover: this checks specifically for the
columns THIS dashboard's queries touch, not a general "is this db exactly
current" check — if a later day adds more schema changes, whatever new
column that day's queries need would need the same treatment. Documented
here so that's a known, deliberate scope limit rather than a surprise.

## Day 9 (continued again) — the fix above had a real, worse mistake in it

Screenshots of the deployed fix showed something I hadn't accounted for:
`/audit` was already displaying 4 rows of genuine agent reasoning — real
sentences like "Risk score 0.85 driven by new/unrecognized customer email
combined with multiple transactions from the same email within the last
hour" — that read nothing like `seed_demo_scenario()`'s canned reason
strings ("Testing mid-risk auto-hold path"). That's real output from an
earlier live Claude Agent SDK run (Day 6 or Day 7 testing), sitting in
`risk_agent.db`, chain-intact and untouched. It makes total sense once you
separate the two tables: Day 7's schema change only added columns to
`transactions`, never touched `agent_actions` — so the audit trail was
always going to read fine regardless of the `on_hold` gap, while the live
feed broke on exactly that one table.

The mistake: my previous fix's only remedy was a "Reset" button, and
`reset()` calls `init_db(fresh=True)`, which deletes the entire db file
and recreates it empty. If you'd clicked the only button the banner
offered, that real historical audit trail — genuinely good material for
the pitch video, and the only surviving evidence of an earlier live run —
would have been gone, permanently, to fix what was actually a one-column
gap in one table. That's a worse failure mode than the crash it replaced:
a crash is obviously wrong and stops you; a "fix" that quietly destroys
real data the moment you click the only button offered is not obvious
until it's too late.

Fixed properly: added `repair_schema(conn)`, which runs `ALTER TABLE
transactions ADD COLUMN ...` for exactly the columns that are missing
(`on_hold INTEGER NOT NULL DEFAULT 0`, `held_at INTEGER`, matching
`sql/schema.sql`'s definitions exactly) and nothing else — SQLite performs
this in place, existing rows keep their data, other tables are untouched.
The banner on `/` now offers "Repair schema" as the primary action with an
explanation of why it's the right default, and keeps "Full reset" as a
clearly-labeled destructive fallback for when someone actually wants to
start over. New `/repair` route, `list[str]`-returning `repair_schema()`
used by it.

Verified for real, not assumed: built a throwaway db with the same
pre-Day-7 `transactions`/`agent_actions` shape as before, but this time
also inserted a real transaction row and a real, properly-hash-chained
`agent_actions` row with genuine-looking reasoning text, to stand in for
exactly what was actually sitting in the real `risk_agent.db`. Confirmed
through Flask's test client: before repair, `/` shows the banner and
`/audit` already shows the real historical row with an intact chain
(matching what the screenshots showed); after `POST /repair`, `/` renders
normally AND still shows the preserved transaction row, and `/audit`
still shows the same historical reasoning text with the chain still
intact — nothing was lost, only the missing columns were added.

The lesson worth keeping: "fix the crash" and "fix it safely" aren't the
same task, and the difference only showed up because real screenshots of
real data surfaced it — a case for looking at what a fix actually does to
existing state, not just whether it stops the traceback.

## Day 9 (continued a third time) — the repair itself left one column wrong

More screenshots, this time of the repaired dashboard actually working —
`pay_scenario_mid` and `pay_scenario_high` rendering with real amounts,
risk scores, and reason codes. But the Hold column said "clear" for both,
while the Last agent decision column said `auto executed` /
`mid_risk_small_amount_hold` for the first one. Those two columns
shouldn't be able to disagree — "auto executed" for `hold_payment` means
`tool_hold_payment` actually ran `UPDATE transactions SET on_hold = 1`
(confirmed by re-reading the function directly: the `auto` tier branch
sets `on_hold = 1, held_at = ...` before logging the action;
`queued_for_approval` deliberately does NOT touch `on_hold` at all — that
tier means nothing has executed yet, which is correct, not a bug).

Root cause, and it's mine: the schema repair from two entries ago used
`ALTER TABLE transactions ADD COLUMN on_hold INTEGER NOT NULL DEFAULT 0`.
SQLite applies that default to every existing row unconditionally — it
has no way to know what the column's value *should* have been for a row
that predates the column's existence. For `pay_scenario_mid`, the correct
value was recoverable — `agent_actions` already has the real
`auto_executed hold_payment` row proving it was actually held — but the
repair never looked at that log, so the column just landed on the
schema's literal default (0/clear) instead. A `DEFAULT` value is a
guess, and here it guessed wrong for exactly the rows that had a real
answer sitting one table over.

Fixed with `backfill_hold_state(conn)`: recomputes `on_hold`/`held_at`
for every payment from its own `agent_actions` history — specifically,
whichever of `hold_payment`/`release_payment` was most recently logged
with `decision_tier` `auto_executed` or `human_approved` (i.e. actually
executed, not merely queued or denied). `repair_schema()` now calls it
automatically right after adding any missing column, and the `/repair`
route calls it unconditionally on every hit — not just when a column was
freshly added — because the db on your machine had already been through
the OLD repair once, meaning the columns already exist and the
"only backfill when we just added a column" guard would otherwise never
fire again for it. Also added a standing "Sync hold state from audit log"
button to the live feed's normal controls (not just the schema-mismatch
banner), since a derived column silently drifting from its source of
truth isn't a one-time migration problem — it's a class of bug that
deserves an always-available, self-service fix, framed honestly as what
it is: an idempotent re-derivation from `agent_actions`, never a guess.

Verified against a hand-built reproduction that mirrors the exact bug —
a `pay_scenario_mid` row with `on_hold=0` but a real `auto_executed
hold_payment` already logged, and a `pay_scenario_high` row that's
genuinely still `queued_for_approval` (never executed). Before the sync:
both showed "clear," matching the screenshots exactly. After
`POST /repair`: `pay_scenario_mid` correctly flips to "on hold,"
`pay_scenario_high` correctly stays "clear" — proving the fix repairs
the real drift without falsely holding a payment that was only ever
queued, not held.

Three build-log entries in a row on what was meant to be one fix. Worth
naming plainly rather than glossing over: the first pass stopped a crash,
the second pass stopped it from being destructive, and it took a third
look at real data to catch that the "safe" repair had quietly written a
wrong fact into the database. Each one only surfaced because real
screenshots of the real dashboard, against the real file on your machine,
were checked rather than assumed correct after the previous fix shipped.

## Day 10 — edge-case testing found two real crashes, both fixed

Started Day 10 with the tracker's own instruction: "test missing fields,
webhook retries, duplicate payment_ids — fix or document." Ran each
against the real code instead of reasoning about it in the abstract.

**Duplicate payment_ids: not reachable, and confirmed why.** Every code
path that inserts into `transactions` (`run_demo()`, `day6/run_scenario.py`,
the dashboard's `/seed`) calls `init_db(fresh=True)` first — checked all
three directly. There's also no live webhook-to-database ingestion
pipeline anywhere in this build (`day2/webhook_listener.py` verifies a
signature and prints; it never writes to `transactions`) — a real,
deliberate scope limit, not an oversight, and now stated as such. Built a
throwaway db and ran a real duplicate `INSERT` against the actual schema
to confirm what WOULD happen if a future ingestion path existed:
`sqlite3.IntegrityError: UNIQUE constraint failed: transactions.payment_id`
— documented, not fixed, since fixing it would mean building a feature
(idempotent webhook ingestion) that's genuinely out of scope for a 10-day
solo build already flagged as a known limitation.

**Webhook retries and missing fields: tested for real, both fine.** Sent
an identical signed body through `/webhook` twice via Flask's test client
— both times 200, byte-identical response, because signature
verification is a pure function and nothing downstream mutates state.
Sent `{}` (a webhook payload missing every field) — 200, no crash,
because the code already uses `payload.get("event")` rather than
`payload["event"]`. Both are real, verified facts now, not assumptions.

**Malformed JSON body with a technically-valid signature: a real crash,
and a real fix.** A signature only proves the sender knew the secret — it
says nothing about whether the body is valid JSON. Sent a body that
doesn't parse (`{not valid json!!`) signed correctly over those exact
bytes: unhandled `json.JSONDecodeError` inside the route, Flask's default
500 handler, full traceback dumped to the terminal. Worse than just an
ugly error: Razorpay's real webhook delivery retries on any non-2xx
response, so a single malformed body would have retried indefinitely
instead of failing once and staying failed. Fixed by wrapping
`json.loads(body)` in a `try/except json.JSONDecodeError`, returning a
clean `400` — signature check still runs first and still rejects a wrong
signature the same way, verified by re-running both cases through the
test client after the fix.

**A second, more serious crash found while testing the first one.** While
setting up a "missing data" test for the agent tools (a payment_id the
system has genuinely never seen — not a malformed one, a well-formed but
unknown one), `tool_hold_payment` crashed: `sqlite3.IntegrityError:
FOREIGN KEY constraint failed`. Root cause: `agent_actions.payment_id`
and `.dispute_id` are real foreign keys into `transactions`/`disputes`
(by design — it's what guarantees every audit-log row ties to something
real), and every `tool_*` function unconditionally calls
`log_agent_action()` with whatever id it was given, even one that was
never inserted anywhere. The existing permission-gate check
(`_validate_tool_input`) only validates the id's *shape* (`pay_.../disp_...`
prefix) — it doesn't check the id actually exists, and it only runs for
calls that go through the live Agent SDK loop at all, not for the six
`day7`/dashboard/test scripts that call `tool_hold_payment` and friends
directly. So a well-formed-but-hallucinated id from the agent, or a typo
in a direct call, would crash the whole call instead of failing cleanly —
a real gap in a project whose entire pitch rests on "the agent never
silently claims success and never just crashes."

Checked all six tool functions that log an action tied to a payment_id or
dispute_id (`tool_hold_payment`, `tool_release_payment`,
`tool_notify_merchant`, `tool_draft_dispute_evidence`,
`tool_submit_dispute_evidence`, `tool_accept_dispute`) — all six had the
identical vulnerability, confirmed by calling each directly against an
unknown id before touching any code. Fixed with one shared helper,
`_not_found_result()`, and an existence check at the top of each of the
six functions, returning a clean `{"status": "not_found", ...}` before
anything else runs (before any live Razorpay call, before
`evaluate_policy()`, before any log write). Deliberately does NOT write
to `agent_actions` for this case — logging against an id that doesn't
exist would either violate the same foreign key or require weakening it,
and an unknown id isn't really "the agent acting on your data," it's an
input-validation failure, the same category `_validate_tool_input`
already denies without logging. Verified for real: called all six
functions with unknown ids and confirmed a clean `not_found` result with
zero rows written to `agent_actions`, then re-ran `--demo` end to end and
confirmed byte-for-byte identical output to before the fix — the guard
adds a check, it doesn't change any real behavior.

Both fixes are cheap, small, and land exactly on this project's own
stated design principle rather than adding new behavior — which is
probably why they were worth finding: a "never crash, always report
honestly" pledge is only as real as the code paths that were actually
tested against it, and two of the eight tool-call paths in this codebase
hadn't been, until today.
