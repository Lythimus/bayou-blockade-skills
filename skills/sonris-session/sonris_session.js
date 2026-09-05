#!/usr/bin/env node
/**
 * sonris-session harness — local use only.
 *
 * Establishes (or checks) the SONRIS session that every other sonris-*
 * skill depends on. Every path under sonlite.dnr.state.la.us/ords/
 * redirects an un-cookied request to SONRIS_CAPTCHA_PKG.SHOW_CAPTCHA_apex,
 * a reCAPTCHA Enterprise challenge. This script cannot and does not solve
 * that challenge — a real person solves it once, in a real browser, and
 * this script's job is capturing that session (cookies AND the full
 * browser-shaped header set/order that came with it) so sonris_get.js can
 * replay it faithfully.
 *
 * A saved session is not just a cookie value. Cloudflare scores the whole
 * request shape — header presence, order, and the TLS/HTTP2 fingerprint
 * underneath it — so the default capture path hands back a complete
 * DevTools "Copy as cURL" of a real solved-session request, not just the
 * cookie string.
 *
 * Ways to establish a session, in order of fingerprint fidelity:
 *   1. (no args)         Paste a "Copy as cURL (bash)" capture on stdin.
 *   2. --curl-file <path> Same, reading the blob from a file.
 *   3. --from-clipboard   Same, via `pbpaste`.
 *   4. --cookie <token>   Quick path: just the cookie, default headers.
 *   5. --headful          Drive a real (stealth-hardened) browser window
 *                         and solve the CAPTCHA live; captures its own
 *                         header set automatically.
 *
 * Usage:
 *   node sonris_session.js                      # paste Copy-as-cURL on stdin
 *   node sonris_session.js --curl-file req.txt
 *   node sonris_session.js --from-clipboard
 *   node sonris_session.js --cookie <token>
 *   node sonris_session.js --headful [--timeout 300]
 *   node sonris_session.js --check [--probe]
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const sessionProfile = require('./lib/session_profile');
const transports = require('./lib/transports');

const { COOKIE_NAME } = sessionProfile;
const PROBE_URL = 'https://sonlite.dnr.state.la.us/ords/r/sonris/ucmsearch/finddocuments?idx=xoperatorcode&val=H1166';

function parseArgs(argv) {
  const args = {
    cookie: null,
    check: false,
    probe: false,
    timeout: 300,
    headful: false,
    curlFile: null,
    fromClipboard: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--cookie') args.cookie = argv[++i];
    else if (a === '--check') args.check = true;
    else if (a === '--probe') args.probe = true;
    else if (a === '--timeout') args.timeout = parseInt(argv[++i], 10);
    else if (a === '--headful') args.headful = true;
    else if (a === '--curl-file') args.curlFile = argv[++i];
    else if (a === '--from-clipboard') args.fromClipboard = true;
    else if (a === '--help' || a === '-h') {
      printHelp();
      process.exit(0);
    } else {
      console.error(`Unknown argument: ${a}`);
      printHelp();
      process.exit(1);
    }
  }
  return args;
}

function printHelp() {
  console.log(`
sonris-session — establish or check the SONRIS session

  (no args)           Print a DevTools walkthrough and read a "Copy as cURL
                       (bash)" capture from stdin (Ctrl-D to finish). This
                       is the default: it captures the full header set and
                       every cookie from a session you already solved
                       yourself, not just a cookie value.
  --curl-file <path>  Same, reading the capture from a file instead of stdin.
  --from-clipboard     Same, reading the capture via \`pbpaste\`.
  --cookie <token>    Quick path: save just the SONRIS_CAPTCHA2.0 value with
                       a default Chrome header set. Faster, but fingerprints
                       worse than a full capture — prefer the default mode.
  --headful           Drive a real, stealth-hardened browser window to
                       SONRIS and wait for you to solve the reCAPTCHA live.
                       Captures the browser's own real header set on success.
  --timeout <seconds> Max seconds to wait for --headful (default: 300).
  --check             Report saved session status: age, cookies present
                       (names only), captured UA, resolved transport.
  --probe             With --check, also issue one live request through the
                       resolved transport and report ok/gated/blocked.

No expiry math is enforced here — the cookie's own lifetime isn't tracked
against a clock. --check --probe tells you empirically whether the session
still works; that's more reliable than assuming a fixed shelf life.
`);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function printCaptureWalkthrough() {
  console.log(`
Establishing a session manually:

  1. In your normal browser, go to https://sonlite.dnr.state.la.us and
     solve the reCAPTCHA if prompted (any SONRIS search page is fine).
  2. Open DevTools -> Network tab, then reload or click a link so a
     request to sonlite.dnr.state.la.us shows up in the list.
  3. Right-click that request -> Copy -> Copy as cURL (bash).
  4. Paste it here and finish with Ctrl-D — or pipe it in directly next
     time: \`pbpaste | node sonris_session.js\` or
     \`node sonris_session.js --curl-file req.txt\`.

Waiting for pasted input on stdin (Ctrl-D to finish, Ctrl-C to abort)...
`);
}

function captureFromCurl(blob, sourceLabel) {
  const profile = sessionProfile.buildProfileFromCurl(blob, { sourceLabel });
  sessionProfile.saveProfile(profile);
  const summary = sessionProfile.summarizeProfile(profile);
  console.log(`Saved session -> ${sessionProfile.PROFILE_FILE}`);
  console.log(`Captured from: ${profile.capturedFrom}`);
  console.log(`User-Agent: ${profile.userAgent}`);
  console.log(`Cookies captured: ${summary.cookieNames.join(', ') || '(none)'}`);
  if (!summary.hasSessionCookie) {
    console.error(`warning: no ${COOKIE_NAME} cookie in the capture — was the CAPTCHA actually solved before this request?`);
    process.exitCode = 1;
  }
}

async function headfulSolve(timeoutSeconds) {
  const { chromium } = require('playwright');
  const stealth = require('./lib/stealth');

  const profileDir = path.join(__dirname, '.pw-profile');
  fs.mkdirSync(profileDir, { recursive: true });

  const context = await stealth.launchStealthContext(chromium, profileDir, { acceptDownloads: true });
  const page = context.pages()[0] || (await context.newPage());

  const capturedRequests = [];
  page.on('request', (req) => {
    if (req.resourceType() === 'document' && req.url().includes('sonlite.dnr.state.la.us')) {
      capturedRequests.push({ url: req.url(), headers: req.headers() });
    }
  });

  try {
    console.log('Opening SONRIS in a visible browser window...');
    await page.goto(PROBE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

    console.log('>>> If a reCAPTCHA challenge appears, solve it in that window now.');
    console.log(`>>> Waiting up to ${timeoutSeconds}s for the ${COOKIE_NAME} cookie to be set...`);

    const deadline = Date.now() + timeoutSeconds * 1000;
    let cookie = null;
    while (Date.now() < deadline) {
      const cookies = await context.cookies('https://sonlite.dnr.state.la.us');
      cookie = cookies.find((c) => c.name === COOKIE_NAME);
      if (cookie) break;
      await new Promise((r) => setTimeout(r, 1500));
    }

    if (!cookie) {
      throw new Error(
        `timed out after ${timeoutSeconds}s waiting for the CAPTCHA to be solved. Re-run with --timeout <n> to allow more time.`
      );
    }

    console.log('CAPTCHA solved, cookie captured. Re-navigating once to capture the post-solve header set...');
    await page.goto(PROBE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});

    const allCookies = await context.cookies('https://sonlite.dnr.state.la.us');
    const cookieMap = {};
    for (const c of allCookies) cookieMap[c.name] = c.value;

    const last = capturedRequests[capturedRequests.length - 1];
    let profile;
    if (last) {
      const headerOrder = [];
      const headerMap = {};
      for (const [name, value] of Object.entries(last.headers)) {
        const lname = name.toLowerCase();
        if (lname === 'cookie') {
          headerOrder.push('cookie');
          continue;
        }
        headerOrder.push(lname);
        headerMap[lname] = value;
      }
      profile = {
        capturedAt: new Date().toISOString(),
        capturedFrom: last.url,
        userAgent: headerMap['user-agent'] || sessionProfile.DEFAULT_UA,
        headerOrder,
        headers: headerMap,
        cookies: cookieMap,
      };
    } else {
      profile = sessionProfile.buildDefaultProfile(cookieMap[COOKIE_NAME], cookieMap);
    }

    sessionProfile.saveProfile(profile);
    console.log(`Saved session -> ${sessionProfile.PROFILE_FILE}`);
    console.log(`Cookies captured: ${Object.keys(cookieMap).join(', ')}`);
  } finally {
    await context.close().catch(() => {});
  }
}

async function reportStatus(opts) {
  const loaded = sessionProfile.loadProfile();
  if (!loaded) {
    console.log('No saved SONRIS session. Run `node sonris_session.js` and paste a Copy as cURL capture.');
    process.exit(1);
    return;
  }
  const { profile, legacy } = loaded;
  const summary = sessionProfile.summarizeProfile(profile);

  console.log(
    legacy
      ? 'Loaded a legacy session (.session/state.json) with a synthesized default header set — re-capture with `node sonris_session.js` for better fingerprint fidelity.'
      : 'Loaded session profile.'
  );
  console.log(`Captured: ${profile.capturedAt}${summary.ageHours != null ? ` (${summary.ageHours.toFixed(1)}h ago)` : ''}`);
  if (summary.ageHours != null && summary.ageHours > 24 * 7) {
    console.log('Note: captured over 7 days ago. That does not necessarily mean it stopped working — use --probe to check empirically.');
  }
  console.log(`User-Agent: ${summary.userAgent}`);
  console.log(`Cookies present: ${summary.cookieNames.join(', ') || '(none)'}`);
  if (!summary.hasSessionCookie) console.log(`warning: no ${COOKIE_NAME} cookie present.`);

  const transport = transports.resolveTransport('auto');
  console.log(`Resolved transport: ${transport}`);

  if (!opts.probe) {
    process.exit(summary.hasSessionCookie ? 0 : 1);
    return;
  }

  console.log('Probing with one live request...');
  try {
    const result = await transports.request(PROBE_URL, profile, { transport: 'auto', as: 'navigate' });
    const classification = transports.classifyResponse(result, { expectBinary: false });
    console.log(`Probe result: HTTP ${result.status} via ${result.transport} -> ${classification.ok ? 'ok' : classification.reason}`);
    process.exit(classification.exitCode);
  } catch (e) {
    console.error(`Probe failed: ${e.message}`);
    process.exit(1);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.check) return reportStatus({ probe: args.probe });

  if (args.cookie) {
    const profile = sessionProfile.buildDefaultProfile(args.cookie);
    sessionProfile.saveProfile(profile);
    console.log(`Saved session -> ${sessionProfile.PROFILE_FILE}`);
    console.log(
      'Saved with a default Chrome header set, not a full capture. For better fingerprint fidelity, re-run with no arguments and paste a "Copy as cURL" capture instead.'
    );
    return;
  }

  if (args.headful) return headfulSolve(args.timeout);

  if (args.curlFile) {
    const blob = fs.readFileSync(args.curlFile, 'utf8');
    return captureFromCurl(blob, `--curl-file ${args.curlFile}`);
  }

  if (args.fromClipboard) {
    const blob = execFileSync('pbpaste', { encoding: 'utf8' });
    return captureFromCurl(blob, '--from-clipboard');
  }

  printCaptureWalkthrough();
  const blob = await readStdin();
  if (!blob.trim()) {
    console.error('error: no input received on stdin. See --help for other capture options.');
    process.exit(1);
    return;
  }
  return captureFromCurl(blob, 'stdin paste');
}

main().catch((e) => {
  console.error(`\nerror: ${e.message}`);
  process.exit(1);
});
