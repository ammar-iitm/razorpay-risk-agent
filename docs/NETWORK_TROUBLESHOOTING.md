# Network Troubleshooting — Cloudflare/ngrok Tunnel Connectivity

Written because of what happened setting up the Day 2 webhook tunnel: `cloudflared`'s
own connectivity precheck reported failures reaching Cloudflare's tunnel
infrastructure over both UDP and TCP on port 7844 — but the tunnel connected
anyway, on a fallback path. This doc explains what that means, why it's
happening on personal (not campus) internet, and what to actually do about
it before it causes a flakier failure on Day 7.

## What actually happened, in plain terms

`cloudflared` tries several ways to reach Cloudflare's edge network. Its
first choice is QUIC (a fast protocol that runs over UDP, port 7844). The
precheck tries to confirm that path works *before* connecting, and both
that and the TCP/HTTP2 fallback to the same port failed. Despite that, the
line `Registered tunnel connection` at the end confirms it found *some*
working route in — Cloudflare's edge is large and reachable multiple ways,
so a failed precheck doesn't always mean a failed tunnel. Right now this is
a performance/reliability risk, not a hard blocker.

## Why this happens on personal internet, verified against Cloudflare's own docs

Per [Cloudflare's official troubleshooting guide](https://developers.cloudflare.com/tunnel/troubleshooting/),
this specific failure (`failed to dial to quic connection ... handshake did
not complete in time`) means your network is blocking outbound UDP on port
7844. On a home connection, the usual suspects, roughly in order of
likelihood:

1. **Your router's firewall/NAT** — many consumer routers block or
   deprioritize "unusual" outbound UDP ports by default, especially
   ISP-provided combo modem/router units.
2. **ISP-level shaping of QUIC traffic** — some ISPs throttle or block QUIC
   specifically (it's often mistaken for video-streaming traffic and
   deprioritized, or blocked outright to force traffic through inspectable
   TCP instead).
3. **A VPN client or security app running locally** — anything that
   intercepts or filters outbound traffic (VPN software, some antivirus
   suites, parental-control apps) can silently drop UDP on non-standard
   ports.
4. **CGNAT** (carrier-grade NAT) — if your ISP doesn't give you a real
   public IP (common on some mobile/fiber ISPs), certain UDP paths behave
   unpredictably. Not something you can fix client-side if this is the
   cause.

## Diagnose which one it is

Run these in your real Terminal (not through Cowork — needs real internet):

```bash
# 1. Is a VPN active? (If this lists anything, disconnect it and retest first — cheapest check)
scutil --nc list

# 2. Direct UDP test to the exact host/port cloudflared complained about
nc -uvz -w 3 region1.v2.argotunnel.com 7844
nc -uvz -w 3 region2.v2.argotunnel.com 7844

# 3. Same test over TCP (tests the HTTP/2 fallback path)
nc -vz -w 3 region1.v2.argotunnel.com 7844
```

If all of these fail even with a VPN off, it's almost certainly your router
or ISP, not your Mac.

**Isolation test — the fastest way to know for sure:** tether your laptop to
your phone's mobile hotspot for two minutes and rerun `cloudflared tunnel
--url http://localhost:5000`. If the precheck passes cleanly on the
hotspot, it's your home router or ISP, not a Mac/software issue. If it
*still* fails on the hotspot, the cause is local (VPN, security software,
or macOS network settings) — much cheaper to fix.

## Fixes, ordered by effort

1. **Force the TCP/HTTP2 fallback explicitly**, skipping the QUIC attempt
   entirely:
   ```bash
   cloudflared tunnel --protocol http2 --url http://localhost:5000
   ```
   Cheapest thing to try — costs nothing, takes 10 seconds, and per
   Cloudflare's own docs this is a supported, if slightly slower, path.

2. **Turn off any VPN or aggressive security/firewall app** while doing
   buildathon work, if the `scutil --nc list` check in the previous section
   showed one active.

3. **Open UDP port 7844 outbound on your router**, if you have access to
   its admin panel (usually `192.168.1.1` or `192.168.0.1` in a browser).
   Look for "Firewall," "Port Filtering," or "Security" settings — you're
   allowing *outbound* UDP 7844, not opening an inbound port, so this is
   low-risk. Exact steps vary a lot by router brand/model.

4. **Call/check your ISP's traffic-shaping policy** — lowest priority to
   chase; most consumer ISPs don't publish this, and it's a slow path to a
   fix compared to the other three.

## If nothing above resolves it before Day 7

You don't strictly need a stable tunnel for the whole build — only for the
minutes you're actively testing webhook delivery. Fallback plan if this
stays flaky:

- Use the **mobile hotspot** as your primary connection specifically during
  webhook testing sessions, and your regular internet the rest of the time.
- Or skip the live webhook test entirely for the pitch video and demo the
  webhook flow using **ngrok's local inspector (`127.0.0.1:4040`) replay
  feature** or a manually crafted signed request instead — slightly less
  impressive than a live Razorpay-triggered webhook, but still proves the
  signature verification and audit logging work, which is the part that
  actually matters for the architecture story.

This is exactly the kind of thing worth a line in `BUILD_LOG.md` once it's
actually resolved one way or another — not urgent to log yet since it's
still in progress.

## Update: the UDP/QUIC precheck wasn't actually the blocker — bot protection was

Diagnosed live on Day 2. The precheck failures above turned out to be a red
herring — `cloudflared` did register a working tunnel connection despite
them. The actual blocker was different and more fundamental: Cloudflare
applies its own bot-protection layer to `trycloudflare.com` (the shared,
anonymous domain quick tunnels use), and it flags automated server-to-server
POST requests — including Razorpay's real webhook deliveries — and blocks
them with a 403 before the request ever reaches the tunnel or the local
Flask app. Confirmed by:

- Manually `curl -v POST`-ing the tunnel URL directly and getting a 403 with
  a legitimate, unmodified TLS cert (ruling out a local firewall/MITM).
- The identical pattern reported by other developers on Cloudflare's own
  community forum for webhook/automation traffic through tunnels.

Because `trycloudflare.com` is Cloudflare's shared anonymous domain (not a
zone you own), there is no WAF/Bot Fight Mode setting available to allowlist
this — same fundamental shape of problem as the ngrok free-tier interstitial
documented earlier in this project, just Cloudflare's version.

**Practical fix:** switch to [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)
instead of an anonymous Cloudflare quick tunnel:

```bash
brew install tailscale
tailscale up            # logs in / creates a free account
tailscale funnel 5000   # exposes localhost:5000 over a stable https:// URL
```

Tied to a real (free) account rather than a shared anonymous domain, and
built specifically for exposing a local service to the internet — should not
carry the same blanket bot-protection on server-to-server traffic.

**Fallback if that also has issues:** skip live webhook delivery for the
demo entirely. Send a manually crafted, correctly-signed payload straight to
`webhook_verify.py` / `webhook_listener.py` on `localhost` — this still
proves the signature-verification and audit-log path work, which is the part
that actually matters for the architecture story, without depending on any
tunnel at all.
