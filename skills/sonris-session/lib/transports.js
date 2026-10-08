/**
 * lib/transports.js — the transport ladder.
 *
 * A captured Chrome header set is only half of what Cloudflare scores. The
 * TLS ClientHello (JA3/JA4), ALPN negotiation, and HTTP/2 SETTINGS + frame
 * ordering happen below the header layer, and Node's undici and system curl
 * both produce fingerprints that match no real browser. Sending a Chrome
 * header set over an undici connection is a *mismatch* — often a stronger
 * bot signal than an honest tool UA would have been. So: prefer whichever
 * transport's low-level fingerprint actually matches the captured headers,
 * and fall back gracefully when it isn't installed.
 *
 *   1. curl-impersonate  — reproduces Chrome's real JA3/JA4 + HTTP/2 SETTINGS
 *   2. real browser      — Playwright + lib/stealth.js; it IS a browser
 *   3. system curl       — header layer exact, TLS layer is curl's
 *   4. node fetch        — last resort
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const IMPERSONATE_CANDIDATES = ['curl_chrome131', 'curl_chrome124', 'curl_chrome116', 'curl-impersonate-chrome'];
const EXTRA_BIN_DIRS = ['/opt/homebrew/bin', '/usr/local/bin'];

const NAVIGATE_PRESET = {
  accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
  'sec-fetch-dest': 'document',
  'sec-fetch-mode': 'navigate',
  'sec-fetch-site': 'same-origin',
  'sec-fetch-user': '?1',
  'upgrade-insecure-requests': '1',
};

const AJAX_PRESET = {
  'sec-fetch-dest': 'empty',
  'sec-fetch-mode': 'cors',
  accept: '*/*',
  'x-requested-with': 'XMLHttpRequest',
};

// Headers that only make sense for one request shape. A profile captured
// from an XHR/ajax request carries origin/content-type/x-requested-with;
// replaying those on a bodyless top-level GET navigation is itself a
// mismatch (no browser sends Origin or Content-Type on a plain nav). The
// reverse (sec-fetch-user, upgrade-insecure-requests) is the same problem
// for a captured navigation profile replayed as ajax.
const NAVIGATE_ONLY_HEADERS = ['sec-fetch-user', 'upgrade-insecure-requests'];
const AJAX_ONLY_HEADERS = ['origin', 'content-type', 'x-requested-with'];

function findBinary(name) {
  const dirs = (process.env.PATH || '').split(':').concat(EXTRA_BIN_DIRS);
  for (const dir of dirs) {
    if (!dir) continue;
    const p = path.join(dir, name);
    try {
      if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    } catch (e) {
      // ignore
    }
  }
  return null;
}

function detectImpersonateBinary() {
  for (const name of IMPERSONATE_CANDIDATES) {
    const p = findBinary(name);
    if (p) return p;
  }
  return null;
}

function detectSystemCurl() {
  return findBinary('curl');
}

function browserTransportAvailable() {
  try {
    require.resolve('playwright');
  } catch (e) {
    return false;
  }
  const stealth = require('./stealth');
  return Boolean(stealth.findChromeExecutable() || stealth.findBraveExecutable() || stealth.hasBundledChromium());
}

function resolveTransport(preferred) {
  if (preferred && preferred !== 'auto') return preferred;
  if (detectImpersonateBinary()) return 'impersonate';
  if (browserTransportAvailable()) return 'browser';
  if (detectSystemCurl()) return 'curl';
  return 'node';
}

function describeAvailability() {
  return {
    impersonate: detectImpersonateBinary(),
    browser: browserTransportAvailable(),
    curl: detectSystemCurl(),
    node: true,
  };
}

/** Builds the final ordered [name, value] header list for a request. */
function buildHeaderList(profile, { as = 'navigate', referer } = {}) {
  const preset = as === 'ajax' ? AJAX_PRESET : NAVIGATE_PRESET;
  const headers = { ...profile.headers, ...preset };
  const stripList = as === 'ajax' ? NAVIGATE_ONLY_HEADERS : AJAX_ONLY_HEADERS;
  for (const name of stripList) delete headers[name];
  if (referer) headers.referer = referer;

  const cookieValue = Object.entries(profile.cookies || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('; ');

  const order = (profile.headerOrder || []).slice();
  if (cookieValue && !order.includes('cookie')) order.push('cookie');
  for (const name of Object.keys(headers)) {
    if (!order.includes(name)) order.push(name);
  }

  const list = [];
  for (const name of order) {
    if (name === 'cookie') {
      if (cookieValue) list.push(['cookie', cookieValue]);
      continue;
    }
    if (headers[name] !== undefined) list.push([name, headers[name]]);
  }
  return list;
}

function redactedHeaderList(headerList) {
  return headerList.map(([name, value]) => (name === 'cookie' ? [name, redactCookieValue(value)] : [name, value]));
}

function redactCookieValue(cookieHeaderValue) {
  return cookieHeaderValue
    .split(';')
    .map((pair) => {
      const idx = pair.indexOf('=');
      if (idx === -1) return pair;
      return `${pair.slice(0, idx)}=<redacted>`;
    })
    .join(';');
}

async function requestViaNode(url, headerList) {
  const headers = Object.fromEntries(headerList);
  const response = await fetch(url, { redirect: 'follow', headers });
  const body = Buffer.from(await response.arrayBuffer());
  return {
    status: response.status,
    finalUrl: response.url || url,
    headers: Object.fromEntries(response.headers.entries()),
    body,
    transport: 'node',
  };
}

function parseHeaderBlockFile(headerFile) {
  let raw = '';
  try {
    raw = fs.readFileSync(headerFile, 'utf8');
  } catch (e) {
    return { headers: {}, statusLine: '' };
  }
  // curl -D appends one header block per hop when following redirects;
  // the last block (after the last blank-line-separated section) is the
  // final response's headers.
  const blocks = raw.split(/\r?\n\r?\n/).filter((b) => b.trim().length);
  const lastBlock = blocks[blocks.length - 1] || '';
  const lines = lastBlock.split(/\r?\n/);
  const statusLine = lines[0] || '';
  const headers = {};
  for (const line of lines.slice(1)) {
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    headers[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim();
  }
  return { headers, statusLine };
}

function requestViaCurlBinary(binPath, url, headerList) {
  const headerFile = path.join(os.tmpdir(), `sonris-hdrs-${process.pid}-${Date.now()}.txt`);
  const args = ['-sS', '-L', '--compressed', '-D', headerFile, '-o', '-'];
  for (const [name, value] of headerList) args.push('-H', `${name}: ${value}`);
  args.push('-w', '\n__SONRIS_EFFECTIVE_URL__%{url_effective}\n__SONRIS_HTTP_CODE__%{http_code}\n');
  args.push(url);

  const result = spawnSync(binPath, args, { maxBuffer: 1024 * 1024 * 300 });
  if (result.error) throw result.error;

  const stdout = result.stdout || Buffer.alloc(0);
  const markerIdx = stdout.lastIndexOf('__SONRIS_EFFECTIVE_URL__');
  let body = stdout;
  let effectiveUrl = url;
  let httpCode = null;
  if (markerIdx !== -1) {
    body = stdout.slice(0, markerIdx);
    const trailer = stdout.slice(markerIdx).toString('utf8');
    const urlMatch = /__SONRIS_EFFECTIVE_URL__(\S*)/.exec(trailer);
    const codeMatch = /__SONRIS_HTTP_CODE__(\d+)/.exec(trailer);
    if (urlMatch) effectiveUrl = urlMatch[1];
    if (codeMatch) httpCode = parseInt(codeMatch[1], 10);
  }
  // trim the single trailing newline curl -w leaves before the trailer
  if (body.length && body[body.length - 1] === 0x0a) body = body.slice(0, -1);

  const { headers, statusLine } = parseHeaderBlockFile(headerFile);
  try {
    fs.unlinkSync(headerFile);
  } catch (e) {
    // ignore
  }
  const statusFromLine = /HTTP\/\S+\s+(\d+)/.exec(statusLine);
  const status = httpCode || (statusFromLine ? parseInt(statusFromLine[1], 10) : 0);

  return { status, finalUrl: effectiveUrl, headers, body, transport: binPath };
}

/** Thrown when the visible browser window goes away mid-run (crash or user closed it). */
class BrowserGoneError extends Error {}

/**
 * One visible browser window for a whole sonris_get.js run. A Chrome
 * start/stop per URL is machine-like to the site, and every launch is
 * another chance of a crash dialog on the user's screen.
 *
 * Documents (dDocname URLs) are fetched from inside a page already on the
 * SONRIS origin rather than navigated to: navigating to a PDF goes through
 * Chrome's download path, which crashes installed Chrome 154 (see
 * stealth.ensurePdfDownloadPref). The fetch carries the session cookies and
 * a same-origin Referer, but its Sec-Fetch shape is cors/empty, not the
 * navigate/document of a clicked link.
 */
class BrowserSession {
  constructor(profile) {
    this.profile = profile;
    this.context = null;
    this.page = null;
    this.gone = false;
    this.closing = false;
  }

  async open() {
    if (this.context) return;
    const { chromium } = require('playwright');
    const stealth = require('./stealth');
    const profileDir = path.join(__dirname, '..', '.pw-profile');
    fs.mkdirSync(profileDir, { recursive: true });

    // A failed launch ends the run: retrying it per URL is a new Chrome (and
    // potentially a new crash dialog) for every remaining URL.
    try {
      this.context = await stealth.launchStealthContext(chromium, profileDir);
      this.context.on('close', () => {
        if (!this.closing) this.gone = true;
      });
      const cookies = Object.entries(this.profile.cookies || {}).map(([name, value]) => ({
        name,
        value,
        domain: 'sonlite.dnr.state.la.us',
        path: '/',
      }));
      if (cookies.length) await this.context.addCookies(cookies);
      this.page = this.context.pages()[0] || (await this.context.newPage());
    } catch (e) {
      this.gone = true;
      if (this.context) await this.close();
      throw new BrowserGoneError(`the browser window failed to start (${e.message})`);
    }
  }

  async close() {
    if (!this.context || this.closing) return;
    this.closing = true;
    await require('./stealth').closeContext(this.context);
  }

  assertAlive() {
    if (this.gone || !this.page || this.page.isClosed()) {
      throw new BrowserGoneError('the browser window closed or crashed mid-run');
    }
  }

  /**
   * Puts the page on the target's origin (once per run) so an in-page
   * fetch is same-origin. Prefers the captured Referer — the page the user
   * was actually on — over a bare origin root.
   */
  async ensureOrigin(url, referer, timeoutMs) {
    const target = new URL(url).origin;
    let current = null;
    try {
      current = new URL(this.page.url()).origin;
    } catch (e) {
      // about:blank
    }
    if (current === target) return;
    let landing = `${target}/`;
    const candidate = referer || this.profile.headers?.referer;
    try {
      if (candidate && new URL(candidate).origin === target) landing = candidate;
    } catch (e) {
      // malformed captured referer — use the origin root
    }
    await this.page.goto(landing, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
    // The landing load is a SONRIS hit of its own; don't follow it with the
    // document request in the same instant.
    await new Promise((r) => setTimeout(r, 2000 + Math.random() * 2000));
  }

  async request(url, { as = 'navigate', referer, timeoutMs = 45000 } = {}) {
    await this.open();
    this.assertAlive();

    const isDocument = Boolean(new URL(url).searchParams.get('dDocname'));
    try {
      if (isDocument || as === 'ajax') {
        await this.ensureOrigin(url, referer, timeoutMs);
        const result = await this.page.evaluate(
          async ({ fetchUrl, ref }) => {
            const init = { credentials: 'include' };
            if (ref) init.referrer = ref;
            const res = await fetch(fetchUrl, init);
            const bytes = new Uint8Array(await res.arrayBuffer());
            let binary = '';
            for (let i = 0; i < bytes.length; i += 0x8000) {
              binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            }
            return {
              status: res.status,
              url: res.url,
              headers: Object.fromEntries(res.headers.entries()),
              bodyBase64: btoa(binary),
            };
          },
          { fetchUrl: url, ref: referer || null }
        );
        return {
          status: result.status,
          finalUrl: result.url,
          headers: result.headers,
          body: Buffer.from(result.bodyBase64, 'base64'),
          transport: 'browser',
        };
      }

      const gotoOpts = { waitUntil: 'domcontentloaded', timeout: timeoutMs };
      if (referer) gotoOpts.referer = referer;
      const response = await this.page.goto(url, gotoOpts);
      if (!response) throw new Error('browser transport got no response before timeout');
      const body = await response.body().catch(() => Buffer.alloc(0));
      return {
        status: response.status(),
        finalUrl: response.url(),
        headers: response.headers(),
        body,
        transport: 'browser',
      };
    } catch (e) {
      if (this.gone || !this.page || this.page.isClosed()) throw new BrowserGoneError(`the browser window closed or crashed mid-run (${e.message})`);
      // A redirect off the SONRIS origin makes the in-page fetch fail CORS
      // with a bare "Failed to fetch"; say so instead of leaving it opaque.
      if (/Failed to fetch/i.test(e.message)) {
        throw new Error(`in-page fetch failed (${e.message}) — the document may redirect to another host; check it once by hand in the browser`);
      }
      throw e;
    }
  }
}

/**
 * Unified request entry point. opts: { transport, as, referer, dryRun,
 * browserSession }. Pass a BrowserSession to reuse one window across a run;
 * without one, the browser transport opens and closes a window per call.
 * Returns { status, finalUrl, headers, body, transport } — or, for
 * dryRun, { dryRun: true, transport, headerList (redacted) }.
 */
async function request(url, profile, opts = {}) {
  const transport = resolveTransport(opts.transport);
  const headerList = buildHeaderList(profile, { as: opts.as, referer: opts.referer });

  if (opts.dryRun) {
    return { dryRun: true, transport, url, headerList: redactedHeaderList(headerList) };
  }

  if (transport === 'impersonate') {
    const bin = detectImpersonateBinary();
    if (!bin) throw new Error('--transport impersonate requested but no curl-impersonate binary was found');
    return requestViaCurlBinary(bin, url, headerList);
  }
  if (transport === 'browser') {
    if (opts.browserSession) return opts.browserSession.request(url, opts);
    const session = new BrowserSession(profile);
    try {
      return await session.request(url, opts);
    } finally {
      await session.close();
    }
  }
  if (transport === 'curl') {
    const bin = detectSystemCurl();
    if (!bin) throw new Error('--transport curl requested but no system curl binary was found');
    return requestViaCurlBinary(bin, url, headerList);
  }
  return requestViaNode(url, headerList);
}

const CLOUDFLARE_BODY_MARKERS = [/Just a moment/i, /Attention Required/i, /__cf_chl/i, /Sorry, you have been blocked/i];

/**
 * Classifies a completed response. Returns { ok, exitCode, reason }.
 * exitCode: 0 ok, 2 CAPTCHA-gated (needs fresh manual capture),
 * 3 transport blocked / edge rejected / wrong content (new — this is the
 * user's actual observed failure mode, distinct from session expiry).
 */
function classifyResponse(result, { expectBinary = false } = {}) {
  const { status, finalUrl, headers, body, transport } = result;

  if (/SHOW_CAPTCHA/i.test(finalUrl || '')) {
    return { ok: false, exitCode: 2, reason: 'Redirected to the CAPTCHA gate — session needs a fresh manual capture.' };
  }

  const cfMitigated = headers && (headers['cf-mitigated'] || headers['cf-ray']);
  const bodyText = Buffer.isBuffer(body) ? body.slice(0, 4096).toString('utf8') : '';
  const looksLikeCloudflareChallenge =
    (status === 403 || status === 503) && (cfMitigated || CLOUDFLARE_BODY_MARKERS.some((re) => re.test(bodyText)));
  if (looksLikeCloudflareChallenge) {
    return {
      ok: false,
      exitCode: 3,
      reason: `Cloudflare challenged the "${transport}" transport (HTTP ${status}). Try a stronger --transport (browser, or install curl-impersonate) — this is not a session problem.`,
    };
  }

  if (status === 502 || status === 504 || (status >= 520 && status <= 527)) {
    return {
      ok: false,
      exitCode: 3,
      reason: `Edge rejected the request (HTTP ${status}) on the "${transport}" transport. Try a stronger --transport, or retry after a longer pause — this is not a session problem.`,
    };
  }

  const contentType = (headers && (headers['content-type'] || '')) || '';
  if (expectBinary && contentType.includes('text/html')) {
    return {
      ok: false,
      exitCode: 3,
      reason: `Expected a document but got an HTML response on the "${transport}" transport — likely blocked, not delivered.`,
    };
  }
  if (!Buffer.isBuffer(body) || body.length === 0) {
    return { ok: false, exitCode: 3, reason: `Empty response body on the "${transport}" transport.` };
  }

  return { ok: true, exitCode: 0, reason: 'ok' };
}

module.exports = {
  resolveTransport,
  describeAvailability,
  detectImpersonateBinary,
  detectSystemCurl,
  browserTransportAvailable,
  buildHeaderList,
  redactedHeaderList,
  redactCookieValue,
  request,
  classifyResponse,
  BrowserSession,
  BrowserGoneError,
  NAVIGATE_PRESET,
  AJAX_PRESET,
};
