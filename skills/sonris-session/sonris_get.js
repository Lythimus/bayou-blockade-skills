#!/usr/bin/env node
/**
 * sonris_get.js — session-authenticated fetch CLI for SONRIS, replaying a
 * manually-captured browser session over the most browser-consistent
 * transport available on the machine.
 *
 * Every sonris-* skill (except la-class-vi, which only hits CAPTCHA-free
 * hosts) shells out to this instead of curl/fetch directly, so the
 * throttle, per-run cap, transport selection, and response classification
 * are enforced in exactly one place. Requires a session already saved by
 * sonris_session.js.
 *
 * Usage:
 *   node sonris_get.js --url <url> [--url <url> ...]
 *   node sonris_get.js --url-file urls.txt --out-dir ./downloads
 *   node sonris_get.js --url <url> --out-dir . --throttle 2500 --max 50
 *   node sonris_get.js --url <url> --transport browser --as ajax
 *   node sonris_get.js --url <url> --dry-run
 *
 * Exit codes: 0 ok, 1 error, 2 CAPTCHA-gated (session needs re-capture),
 * 3 transport blocked / edge rejected the request (NOT session expiry —
 * see the classification table in lib/transports.js).
 */

const path = require('path');
const fs = require('fs');

const sessionProfile = require('./lib/session_profile');
const transports = require('./lib/transports');

function parseArgs(argv) {
  const args = {
    urls: [],
    urlFile: null,
    outDir: null,
    throttle: 2500,
    max: 200,
    transport: 'auto',
    as: 'navigate',
    referer: null,
    dryRun: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--url') args.urls.push(argv[++i]);
    else if (a === '--url-file') args.urlFile = argv[++i];
    else if (a === '--out-dir') args.outDir = argv[++i];
    else if (a === '--throttle') args.throttle = parseInt(argv[++i], 10);
    else if (a === '--max') args.max = parseInt(argv[++i], 10);
    else if (a === '--transport') args.transport = argv[++i];
    else if (a === '--as') args.as = argv[++i];
    else if (a === '--referer') args.referer = argv[++i];
    else if (a === '--dry-run') args.dryRun = true;
    else if (a === '--help' || a === '-h') {
      printHelp();
      process.exit(0);
    } else {
      console.error(`error: unknown argument "${a}" (run with --help for the flag list)`);
      process.exit(1);
    }
  }
  if (args.urlFile) {
    const lines = fs
      .readFileSync(args.urlFile, 'utf8')
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    args.urls.push(...lines);
  }
  if (args.urls.length === 0) {
    console.error('error: pass one or more --url <url>, or --url-file <path>');
    process.exit(1);
  }
  if (!['navigate', 'ajax'].includes(args.as)) {
    console.error(`error: --as must be "navigate" or "ajax", got "${args.as}"`);
    process.exit(1);
  }
  return args;
}

function printHelp() {
  console.log(`
sonris_get.js — session-authenticated fetch for SONRIS, transport-ladder replay

  --url <url>          URL to fetch. Repeatable.
  --url-file <path>    File of newline-separated URLs, merged with --url.
  --out-dir <dir>      Save each response body to a file here (name from
                        Content-Disposition, else the URL's dDocname/last
                        path segment). Without this, bodies print to stdout,
                        one JSON line per URL.
  --throttle <ms>      Minimum delay between requests (default: 2500), plus
                        a right-skewed random jitter and an occasional
                        longer pause so the cadence isn't a uniform block —
                        pacing courtesy, not evasion. Enforced across runs
                        too (timestamp in .session/), so calling this once
                        per URL from a loop is paced the same as a batch.
  --max <n>            Max URLs to fetch in this run (default: 200).
  --transport <t>      auto (default) | impersonate | browser | curl | node
                        auto picks the best available: curl-impersonate >
                        real browser > system curl > node fetch. See
                        lib/transports.js for why order matters — a Chrome
                        header set over the wrong TLS/HTTP2 fingerprint is a
                        mismatch, which is a stronger bot signal than an
                        honest tool signature would have been.
  --as <navigate|ajax> Header preset to apply (default: navigate). Use
                        "ajax" for wwv_flow.ajax / LOV endpoints.
  --referer <url>      Overrides the captured Referer for this request.
  --dry-run            Print the exact request that would be sent (headers
                        in order, cookie values redacted) without sending it.

The browser transport opens ONE visible window for the whole run and quits
it cleanly at the end, so pass every URL for a step in one call (--url-file)
rather than one call per URL.

Exit codes: 0 ok, 1 error, 2 CAPTCHA-gated (run sonris_session.js again),
3 transport blocked or edge rejected the request (see printed reason —
this is NOT the same as session expiry; try a stronger --transport),
4 the browser window crashed or was closed mid-run (remaining URLs are
written to a resume file; do not loop on this — find out why first).
`);
}

const LAST_REQUEST_FILE = path.join(__dirname, '.session', 'last_request');

function readLastRequest() {
  try {
    return parseInt(fs.readFileSync(LAST_REQUEST_FILE, 'utf8'), 10) || 0;
  } catch (e) {
    return 0;
  }
}

function writeLastRequest() {
  try {
    fs.mkdirSync(path.dirname(LAST_REQUEST_FILE), { recursive: true });
    fs.writeFileSync(LAST_REQUEST_FILE, String(Date.now()));
  } catch (e) {
    // pacing still holds within this run
  }
}

/**
 * Waits until `delay` ms have passed since the last SONRIS request from any
 * run, so a shell loop calling this once per URL is paced like one batch.
 */
async function waitForTurn(delay) {
  const since = Date.now() - readLastRequest();
  if (since < delay) await new Promise((r) => setTimeout(r, delay - since));
}

function filenameFor(url, headers) {
  const cd = headers['content-disposition'];
  if (cd) {
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    if (m) return decodeURIComponent(m[1]);
  }
  try {
    const u = new URL(url);
    const dDocname = u.searchParams.get('dDocname');
    if (dDocname) {
      const ct = headers['content-type'] || '';
      const ext = ct.includes('pdf') ? '.pdf' : '';
      return `${dDocname}${ext}`;
    }
    // idx/val searches all share one path; name them by query so a batch of
    // searches saved with --out-dir doesn't overwrite itself.
    const idx = u.searchParams.get('idx');
    const val = u.searchParams.get('val');
    if (idx && val) return `search_${idx}_${val.replace(/[^A-Za-z0-9._-]+/g, '_')}.html`;
    const last = u.pathname.split('/').filter(Boolean).pop();
    return last || 'download';
  } catch (e) {
    return `download-${Date.now()}`;
  }
}

/** Right-skewed delay so the inter-request histogram isn't a uniform block. */
function nextDelay(baseMs, index) {
  const u = Math.random() || 1e-9;
  const skew = -Math.log(u) * (baseMs * 0.25); // log-normal-ish tail
  let delay = baseMs + Math.min(skew, baseMs * 1.5);
  if (index > 0 && index % 15 === 0) delay += baseMs * (2 + Math.random() * 2); // occasional longer pause
  return Math.round(delay);
}

let activeBrowserSession = null;

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const loaded = sessionProfile.loadProfile();
  if (!loaded) {
    console.error('No saved SONRIS session found.');
    console.error('Run: node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js');
    process.exit(2);
    return;
  }
  const { profile, legacy } = loaded;
  if (legacy) {
    console.error('note: replaying from a legacy state.json cookie with a synthesized header set — re-capture for better fidelity.');
  }
  if (!profile.cookies || !profile.cookies[sessionProfile.COOKIE_NAME]) {
    console.error(`No ${sessionProfile.COOKIE_NAME} cookie in the saved session.`);
    console.error('Run: node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js');
    process.exit(2);
    return;
  }

  const urls = args.urls.slice(0, args.max);
  if (args.urls.length > args.max) {
    console.error(`Note: ${args.urls.length} URLs given, capped at --max ${args.max} for this run. Re-run for the rest.`);
  }

  if (args.dryRun) {
    const url = urls[0];
    const dry = await transports.request(url, profile, { transport: args.transport, as: args.as, referer: args.referer, dryRun: true });
    console.log(`transport: ${dry.transport}`);
    console.log(`GET ${url}`);
    for (const [name, value] of dry.headerList) console.log(`  ${name}: ${value}`);
    return;
  }

  if (args.outDir) fs.mkdirSync(args.outDir, { recursive: true });

  const transport = transports.resolveTransport(args.transport);
  const browserSession = transport === 'browser' ? new transports.BrowserSession(profile) : null;
  activeBrowserSession = browserSession;

  // Every way out of this process quits the window cleanly: a window left
  // behind is an orphan, and a killed one is a crash dialog for the user.
  const finish = async (code) => {
    if (browserSession) await browserSession.close();
    process.exit(code);
  };
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => {
      console.error(`\n${sig} — closing the browser window and stopping.`);
      finish(130);
    });
  }

  let failures = 0;
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    await waitForTurn(nextDelay(args.throttle, i));

    let result;
    try {
      result = await transports.request(url, profile, {
        transport,
        as: args.as,
        referer: args.referer,
        browserSession,
      });
    } catch (e) {
      writeLastRequest();
      if (e instanceof transports.BrowserGoneError) {
        const rest = urls.slice(i);
        const resumeFile = path.join(args.outDir || process.cwd(), `sonris_resume_${Date.now()}.txt`);
        fs.writeFileSync(resumeFile, rest.join('\n') + '\n');
        console.error(`[${i + 1}/${urls.length}] ${e.message}`);
        console.error(`Stopped. ${rest.length} URL(s) not fetched, saved to ${resumeFile}`);
        console.error('Resume later with --url-file; do not relaunch in a loop.');
        await finish(4);
        return;
      }
      failures++;
      console.error(`[${i + 1}/${urls.length}] FAILED ${url}: ${e.message}`);
      continue;
    }
    writeLastRequest();

    // Only document URLs must come back as binary; search pages saved with
    // --out-dir are legitimately HTML.
    const expectBinary = Boolean(new URL(url).searchParams.get('dDocname'));
    const classification = transports.classifyResponse(result, { expectBinary });

    if (!classification.ok) {
      console.error(`[${i + 1}/${urls.length}] ${classification.reason} (${url})`);
      if (classification.exitCode === 2) {
        console.error('Run: node ~/.claude/plugins/bayou/skills/sonris-session/sonris_session.js');
      }
      await finish(classification.exitCode);
      return;
    }

    if (args.outDir) {
      const fname = filenameFor(url, result.headers);
      const dest = path.join(args.outDir, fname);
      fs.writeFileSync(dest, result.body);
      console.log(`[${i + 1}/${urls.length}] ${result.status} ${url} -> ${dest} (${result.body.length} bytes, via ${result.transport})`);
    } else {
      console.log(JSON.stringify({ url, status: result.status, transport: result.transport, body: result.body.toString('utf8') }));
    }
  }

  if (failures) console.error(`${failures} of ${urls.length} URL(s) failed; see FAILED lines above.`);
  await finish(failures ? 1 : 0);
}

main().catch(async (e) => {
  console.error(`\nerror: ${e.message}`);
  if (activeBrowserSession) await activeBrowserSession.close();
  process.exit(1);
});
