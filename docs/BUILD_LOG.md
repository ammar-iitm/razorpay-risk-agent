# Build Log — what broke, and how I fixed it

Kept live, in first person, as it actually happened — not reconstructed
after the fact for the application. This is raw material for the
"explain technical failures and how you recovered" part of the buildathon
submission; trim and polish before pasting in, but the substance here is
real debugging, not a tidied-up story.

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

---

*(new entries append below this line as the build continues)*
