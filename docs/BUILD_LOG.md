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

---

*(new entries append below this line as the build continues)*
