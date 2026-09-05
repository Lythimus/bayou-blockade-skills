---
name: sonris-session
description: Establish or check the SONRIS session that every other SONRIS skill depends on, by capturing a browser session the user already solved a reCAPTCHA in
allowed-tools: Bash, AskUserQuestion
---

# SONRIS Session

SONRIS (`sonlite.dnr.state.la.us`) — Louisiana's Strategic Online Natural Resources
Information System, the system of record for oil/gas/injection wells, permits, and the
Class VI carbon-sequestration program — gates **every** path under `/ords/` behind a
reCAPTCHA Enterprise challenge sitting in front of Cloudflare. An un-cookied request 302s
to `SONRIS_CAPTCHA_PKG.SHOW_CAPTCHA_apex`, site-wide, regardless of which page was
requested.

**A saved session is more than a cookie.** Cloudflare scores the whole shape of a
request — which headers are present, their order, and the TLS/HTTP2 fingerprint
underneath them — not just whether a valid `SONRIS_CAPTCHA2.0` cookie is attached. A
request that carries a perfectly valid cookie can still get an edge-level block (a 504,
or a Cloudflare interstitial page) if its header set or transport fingerprint doesn't
look like a browser. This skill's job is capturing a *complete* session — cookies, full
header set, and header order — from a request the user's own browser actually made, and
`sonris_get.js` replays it over whichever transport on this machine best matches that
browser's fingerprint.

**This does not, and will not, solve the CAPTCHA automatically.** No solver service. The
challenge gets solved by a real person, once, in their own browser. Everything
downstream of that is what gets automated.

**This is local-only.** The session profile is saved to `.session/profile.json` next to
this script — gitignored, never committed, never shared off this machine.

> **Ban-risk note (accepted by the user for this project):** SONRIS's Terms of Use
> discourage automated access and describe a 7-day IP ban for detected bot-like behavior.
> `sonris_get.js` throttles requests and caps them per run specifically to reduce that
> risk, but it does not eliminate it. A permanent block (e.g. a known-bad IP range like
> TOR) shows a "Sorry, you have been blocked" page; a Cloudflare-level challenge or
> rejection on an otherwise-valid session shows up as a 403/503 challenge page or a 502/504
> — see the exit-code table below for how `sonris_get.js` tells these apart. If bulk data
> becomes the actual need, SONRIS's paid Data Subscription Service is the sanctioned
> path — mention it if a search is turning into hundreds of requests.

## Prerequisites

One-time setup, from this skill's directory:

```bash
cd ~/.claude/plugins/bayou/skills/sonris-session
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

Reuses whatever Chromium build Playwright already has cached
(`~/Library/Caches/ms-playwright/`), or a real installed Chrome/Brave if present — see
"Transports" below. If `node -e "require.resolve('playwright')"` run from this directory
succeeds, setup is done.

## Checking session status

Before doing anything else in a `sonris-*` skill, check whether a usable session already
exists:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js --check
```

Add `--probe` to actually issue one live request and confirm the session works, rather
than just reporting what's on disk — more reliable than guessing from age, since expiry
isn't the failure mode here (see below):

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js --check --probe
```

If it reports a working session, skip straight to the calling skill's own work — don't
re-prompt for a CAPTCHA solve unnecessarily.

## Establishing a session — manual capture is the default

**1. Manual capture (default):** the user solves the CAPTCHA in their own real browser
(which already has real cookies, plugins, and a matching TLS fingerprint — nothing to
fake), then hands that request back:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js
```

Walk the user through it:
> 1. In your normal browser, go to `https://sonlite.dnr.state.la.us` and solve the
>    reCAPTCHA if prompted (any SONRIS search page works).
> 2. Open DevTools → Network tab, then reload or click a link so a request to
>    `sonlite.dnr.state.la.us` appears in the list.
> 3. Right-click that request → Copy → **Copy as cURL (bash)**.
> 4. Paste it into the terminal running the command above, then press Ctrl-D.

This captures the full header set (in the order the browser sent it) and every cookie —
not just `SONRIS_CAPTCHA2.0`, but the APEX `ORA_WWV_*` session cookies that travel
alongside it. That's what makes the replay in `sonris_get.js` look like the same browser,
not a script wearing its cookie.

Faster variants of the same idea:
- `--curl-file <path>` — read the paste from a file instead of stdin.
- `--from-clipboard` — read it via `pbpaste` (skip the paste-into-terminal step).
- `--cookie "<token>"` — quick path if only the cookie value is at hand. Saves it with a
  default Chrome header set rather than a captured one — works, but fingerprints worse
  than a full capture. Prefer the default mode when practical.

**2. Headful solve**, if a full capture isn't practical (e.g. no comfort with DevTools) or
the user doesn't already have SONRIS open:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js --headful
```

Tell the user first: **a visible, stealth-hardened browser window will open** on SONRIS
(the real installed Chrome/Brave if found, Playwright's bundled Chromium otherwise — see
"Transports"). If a reCAPTCHA challenge appears, they solve it in that window — nothing
else needs to be touched. The script waits for the resulting cookie, then re-navigates
once to capture the browser's own real header set, and saves both. Waits up to
`--timeout` seconds (default 300).

## Transports (why `sonris_get.js` doesn't just use the captured headers directly)

A captured Chrome header set is only half of what a bot-detector scores. The TLS
handshake and HTTP/2 frame layer underneath it are a separate fingerprint (JA3/JA4,
ALPN negotiation, SETTINGS ordering) — and **putting a Chrome header set on a
non-Chrome connection is a mismatch, which reads as a stronger bot signal than an
honest tool signature would have.** So `sonris_get.js --transport auto` (the default)
picks the best-matching transport actually available on this machine, in order:

1. **`curl-impersonate`** — reproduces Chrome's real TLS/HTTP2 fingerprint. Best fidelity.
   Not installed by default; if the user wants to install it,
   `brew install curl-impersonate` provides `curl_chrome131` etc.
2. **Real browser** (Playwright + stealth hardening) — nothing to spoof, it *is* a
   browser. Slower per-request; used automatically when tier 1 isn't available.
3. **System `curl`** — exact header layer and order, but curl's own TLS fingerprint.
4. **Node `fetch`** — last resort.

Force a specific tier with `--transport <impersonate|browser|curl|node>` if needed (e.g.
to compare behavior across tiers while debugging a block). Use `--dry-run` to print the
exact headers a request would send, in order, with cookie values redacted — useful to
eyeball against DevTools without spending a real request.

## Using the session from other skills

Other skills never touch the session file directly — they call:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_get.js \
  --url "<constructed SONRIS URL>" --throttle 2500
```

`sonris_get.js` loads the saved session, throttles between requests with jittered pacing,
caps how many it'll do in one run, replays the captured headers (with a `navigate` or
`ajax` preset layered on top — pass `--as ajax` for `wwv_flow.ajax`/LOV endpoints), and
classifies the response rather than trusting it blindly. See its `--help` for the full
flag set.

## Exit codes (`sonris_get.js` and `sonris_session.js --check --probe`)

| Code | Meaning | What to do |
|---|---|---|
| **0** | ok | — |
| **1** | script error (bad args, file I/O, etc.) | read the error message |
| **2** | CAPTCHA-gated — no session, or the current one no longer carries a valid `SONRIS_CAPTCHA2.0` cookie | re-run `sonris_session.js` for a fresh capture |
| **3** | the request was **blocked or rejected**, not gated — a Cloudflare challenge page, a 502/504/52x, or an unexpected HTML body where a document was expected | **not a session problem.** Try a stronger `--transport` (e.g. `browser`, or install curl-impersonate); if it persists, the IP itself may be rate-limited or temporarily blocked — pause and retry later rather than escalating requests |

**Exit 2 and exit 3 are different failures and should not be treated the same way.**
Historically every failure here got blamed on "session expired" — that framing is wrong
often enough that it's worth stating plainly: a valid cookie riding a bad transport
fingerprint produces exit 3, not exit 2, and re-running the CAPTCHA solve won't fix it.

## Troubleshooting

- **`sonris_session.js` exits 1 with "no input received on stdin"** — the default mode
  waits for a pasted "Copy as cURL" blob; either paste one and press Ctrl-D, or use
  `--curl-file`/`--from-clipboard`/`--cookie`/`--headful` instead.
- **`--headful` timed out waiting for the cookie** — re-run with a larger `--timeout`, or
  check the browser window wasn't closed/backgrounded during the wait.
- **`sonris_get.js` exits 2** — no session, or the captured cookie isn't in the profile;
  run `sonris_session.js` again.
- **`sonris_get.js` exits 3** — the transport got challenged or rejected, not the
  session. Read the printed reason (it names the transport and HTTP status); try
  `--transport browser`, or if already on `browser`, consider pausing longer between
  requests — this is the code path that replaces the old, misleading "session expired"
  message for the 504s this project was actually seeing.
- **A downloaded file looks like an HTML error page, not a PDF** — `sonris_get.js` now
  checks this itself (exit 3, file not written) rather than saving it silently; if it
  slipped through anyway, `file <path>` will show `HTML document` instead of `PDF
  document`.

$ARGUMENTS
