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
   browser. Slower per-request; used automatically when tier 1 isn't available. See
   "The browser transport" below for how it behaves.
3. **System `curl`** — exact header layer and order, but curl's own TLS fingerprint.
4. **Node `fetch`** — last resort.

Force a specific tier with `--transport <impersonate|browser|curl|node>` if needed (e.g.
to compare behavior across tiers while debugging a block). Use `--dry-run` to print the
exact headers a request would send, in order, with cookie values redacted — useful to
eyeball against DevTools without spending a real request.

## The browser transport

- **One visible window per `sonris_get.js` run.** It opens once, every URL in the run goes
  through it, and it quits cleanly at the end (CDP `Browser.close`, the same as Cmd-Q).
  Keep it visible (`headless: false` is the default). The user believes a hidden window
  invites a ban, and a visible one lets them see what is being fetched.
- **Documents are fetched from inside the page, not navigated to.** For a `dDocname`
  URL, the window first lands on the captured Referer page (once per run, with a
  2–4 s pause after it), then runs a same-origin `fetch` from there. For the current
  capture, that landing page is `…/ords/r/sonris_pub/document_access/home`; without a
  same-origin Referer it is the site root. The fetch carries the session cookies and a
  same-origin Referer. Its `Sec-Fetch-Mode`/`Dest` are `cors`/`empty`, not the
  `navigate`/`document` of a clicked link, so it is a real browser request with a different
  shape. This avoids Chrome's download handler:
  on 2026-10-07, installed Chrome 154.0.8037.98 crashed (`EXC_BAD_ACCESS`, about 3 s after
  launch) on **every** Playwright-managed PDF download. That was 13 "Google Chrome quit
  unexpectedly" dialogs in 11 minutes and about half the downloads lost. It reproduced
  offline against a local PDF, so the cause was not SONRIS.
- **Untested against SONRIS (as of 2026-10-07):** how SONRIS treats the in-page fetch shape,
  and whether `redirectUrl.jsp` redirects off `sonlite.dnr.state.la.us`. For the first
  live use, run one search and one download, then stop and check them. If it does, the in-page fetch fails with an "in-page fetch
  failed … may redirect to another host" error. If you see that, open one document by hand
  in the user's browser to see where it lands; don't switch transports to work around it.
- **Batch each step into one call** (`--url-file`): all searches in one run, then all
  downloads in another. Calling once per URL from a shell loop opens and closes a window per
  URL. That looks machine-like to the site, and each launch is another chance of a crash
  dialog on the user's screen.
- **One window per run doesn't make it faster.** The throttle and `--max` are unchanged.
  The minimum gap is also enforced across runs (timestamp in `.session/last_request`), so a
  loop of single-URL calls is paced like one batch. Don't lower `--throttle` to compensate
  for anything.
- **If the window crashes or is closed mid-run**, `sonris_get.js` stops (exit 4) instead of
  relaunching. It writes the unfetched URLs to `sonris_resume_<ts>.txt` in the output
  directory. Find out why before resuming, and never retry in a loop.
- `--transport curl` for downloads (Chrome headers over curl's TLS) is **untested** and is
  exactly the fingerprint mismatch described above. Don't try it against SONRIS to get
  around a browser problem.

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
flag set. Unknown flags are rejected with a one-line error (`--out` is not `--out-dir`).

With `--out-dir`, documents are saved under the name the server gives (Content-Disposition,
for example `23453427~1.pdf`; the `~1` likely comes from the server, not from collision
handling) or else
`<dDocname>.pdf`. `idx`/`val` search pages are saved as `search_<idx>_<val>.html`. Existing
files with the same name are overwritten.

## Registered-account login (`sonris_login.js`) — a separate, deeper tier

The anonymous CAPTCHA-passed session above gets past the edge gate but never
authenticates as anyone. Some SONRIS pages go a step further and redirect even a
CAPTCHA-passed anonymous session to a login form — e.g. a CUP (Coastal Use Permit)
application's "View Comments" page (`f?p=129:560`), which turns out to be the
**interagency review comment log** (CPRA, LDWF, State Land Office, DCE, etc.), not a
public notice/comment period. That page requires a registered SONRIS account.

If the user has one, credentials go in `~/.claude/bayou-credentials.md` under `SONRIS_USERNAME`
/ `SONRIS_PASSWORD` (see `bayou-credentials.example.md`). Log in and, optionally, fetch one
authenticated page in the same browser session:

```bash
node ~/.claude/plugins/bayou/skills/sonris-session/sonris_login.js \
  --username "$SONRIS_USERNAME" --password "$SONRIS_PASSWORD" \
  --then-url 'https://sonlite.dnr.state.la.us/ords/f?p=129:560:SESSION:::0:P560_CUP_NUM:P20260152'
```

Oracle APEX mints a fresh numeric session/instance ID on login that can't be known in
advance, so a `--then-url` can't hardcode one — pass the literal token `SESSION` where the
instance ID goes and the script substitutes the real post-login ID it landed on. Prints
`{url,finalUrl,status,body}` as JSON on success. Drives a real stealth-hardened Playwright
browser end to end (fill form, click "Log In", follow the resulting navigation) rather than
replaying a raw POST, because APEX page submissions carry a per-page CSRF/session-state
checksum that a static replay can't reconstruct.

Saves the authenticated cookies to `.session/auth_profile.json` — separate from
`.session/profile.json` (the anonymous capture every other `sonris-*` skill shares), so
logging in here never overwrites that.

Confirmed working 2026-09-06 against a real CUP application's comments page.

Exit codes: `0` ok, `1` script error, `2` login failed (bad credentials, or the login
form's markup changed and the `#P101_USERNAME`/`#P101_PASSWORD`/"Log In" selectors no
longer match — check by hand before assuming credentials are wrong).

## Exit codes (`sonris_get.js` and `sonris_session.js --check --probe`)

| Code | Meaning | What to do |
|---|---|---|
| **0** | ok | — |
| **1** | script error (bad args, file I/O, etc.), or one or more URLs in the run failed (each printed as a `FAILED` line; the rest of the run still completed) | read the error message |
| **2** | CAPTCHA-gated — no session, or the current one no longer carries a valid `SONRIS_CAPTCHA2.0` cookie | re-run `sonris_session.js` for a fresh capture |
| **3** | the request was **blocked or rejected**, not gated — a Cloudflare challenge page, a 502/504/52x, or an unexpected HTML body where a document was expected | **not a session problem.** Try a stronger `--transport` (e.g. `browser`, or install curl-impersonate); if it persists, the IP itself may be rate-limited or temporarily blocked — pause and retry later rather than escalating requests |
| **4** | the browser window crashed or was closed mid-run (browser transport only) | unfetched URLs are in `sonris_resume_<ts>.txt`; see the "quit unexpectedly" item under Troubleshooting before resuming |

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
- **"Google Chrome quit unexpectedly" dialogs, or exit 4.** Check the crash reports first,
  without sending any SONRIS traffic:
  `ls -t ~/Library/Logs/DiagnosticReports | rg "Google Chrome"`. A report whose
  `parentProc` is `node` came from this tool, not the user's own Chrome. Things to check:
  - **Pending Chrome update.** If the user's own Chrome has been running since before an
    update, the app on disk is newer than the running one:
    `defaults read "/Applications/Google Chrome.app/Contents/Info" CFBundleShortVersionString`
    compared with `chrome://version`. Ask them to quit and reopen Chrome, then retry.
  - **Reproduce offline.** Serve a local PDF with
    `python3 -I -m http.server --bind 127.0.0.1` and run `sonris_get.js --transport browser
    --out-dir <dir> --url "http://127.0.0.1:8000/x.pdf?dDocname=T1"` against it. A crash
    there is environmental, so stop and tell the user rather than spending SONRIS requests
    on it.
  - Don't silence the dialog (`defaults write com.apple.CrashReporter …`). That's a system
    setting, and it hides the signal.
- **A window that never quits.** Every exit path, including Ctrl-C/SIGTERM and errors,
  closes the window. If one is left behind (for example after `kill -9` of node), quit it
  with Cmd-Q rather than killing it.
- **A downloaded file looks like an HTML error page, not a PDF** — `sonris_get.js` now
  checks this itself (exit 3, file not written) rather than saving it silently; if it
  slipped through anyway, `file <path>` will show `HTML document` instead of `PDF
  document`.

$ARGUMENTS
