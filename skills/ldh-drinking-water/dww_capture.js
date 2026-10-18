#!/usr/bin/env node
/**
 * dww_capture.js: records the LDH Drinking Water Viewer's sample, violation and site-visit grids for one
 * water system from a visible browser. dww.py reads what it records.
 *
 * Why a browser: for anonymous users each of those grids needs a reCAPTCHA pass. The viewer's own page asks
 * Google for a token; when Google is unsure it shows the "I'm not a robot" checkbox, which a person clicks.
 * After a pass LDH gives that browser a 20-minute skip cookie, during which the viewer itself calls the grids
 * with no token. This script opens each page so the viewer makes its own first call (and shows the checkbox
 * if needed), then, while the pass lasts, asks the same grid for the requested date window from inside that
 * page, the way the viewer does. Inside the page it reads only the anti-forgery cookie (XSRF-TOKEN), which
 * the viewer itself echoes as a header; it never solves, requests, reads or replays a reCAPTCHA token or the
 * pass cookies, and nothing leaves the browser except the grid rows it writes to disk. A refused call is never
 * retried on its own: the page is reopened so the person can pass the check again, and a gateway refusal ends
 * the run.
 *
 * Usage:
 *   node dww_capture.js --pws LA1089001                         (all pages, last 10 years)
 *   node dww_capture.js --pws LA1089001 --pages chem,violations --since 2016-01-01
 *
 * Pages: chem (Chemical Samples, then the Lead & Copper Summaries tab), micro (Coliform Samples),
 * violations (Violations), visits (Site Visits).
 *
 * Output: ~/.cache/bayou/ldh-drinking-water/captured/<PWSID>/<Widget>__<query hash>.json
 * Exit codes: 0 every grid complete, 1 script error, 3 some grid incomplete (the browser was left open for
 * the person to finish by hand), 4 nothing captured, 5 LDH's gateway refused this IP.
 */

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const LDH = 'https://sdw.ldh.la.gov/';
const OUT = path.join(os.homedir(), '.cache', 'bayou', 'ldh-drinking-water', 'captured');
const PAGES = {
  chem: 'ChemResults',
  micro: 'MicroResults',
  violations: 'ViolationsEnforcements',
  visits: 'SiteVisits',
};
// Only these grids are written. The viewer also loads contact lists (names, phones, emails of system
// staff) on some pages; they are not needed and are never recorded.
const WIDGETS = new Set([
  'ChemicalGrid', 'SamplingColiformGrid', 'SamplingNonColiformGrid', 'SamplingMicrobialSummariesGrid',
  'LeadAndCopperSummGrid', 'Violations', 'SiteVisits',
]);
const PAGING = new Set(['$skip', '$top', '$count', 'wv']);
// The largest page each grid offers in its own page-size control.
const TOP = { Violations: 100, SiteVisits: 100 };
// Never ask for more than the viewer itself can: its pager stops at 1,000 rows, so a fuller window is split
// into shorter ones instead of paged further. LDH's gateway has refused a quick run of 1,000-row requests;
// whether volume, pace or paging tripped it is unknown, so requests are also spaced at a person's pace.
const REACH = 1000;
const GAP = 8000;
// LDH stops a search at 5,000 result rows (a sample's nested results each count), before sorting, and its
// row count then describes the cut-off set. A window near that total is split, never taken as complete.
const RESULT_CAP = 4500;
// [route, tab, widget, label, one search per calendar year]. The sample grids are searched year by year so
// that no window comes near the result cap.
const JOBS = {
  chem: [['ChemResults', null, 'ChemicalGrid', 'Chemical Samples', true],
         ['ChemResults', '#LeadAndCopperSummGrid-tab', 'LeadAndCopperSummGrid', 'Lead & Copper Summaries', false]],
  micro: [['MicroResults', null, 'SamplingColiformGrid', 'Coliform Samples', true]],
  violations: [['ViolationsEnforcements', null, 'Violations', 'Violations', false]],
  visits: [['SiteVisits', null, 'SiteVisits', 'Site Visits', false]],
};
const DAY = 86400000;

/** Local calendar date: the UTC date runs a day ahead in Louisiana evenings. */
function localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function parseArgs(argv) {
  const today = new Date();
  const ago = new Date(today); ago.setFullYear(today.getFullYear() - 10);
  const a = { pws: null, pages: Object.keys(PAGES), timeout: 1800, since: localIso(ago), until: localIso(today) };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--pws') a.pws = String(argv[++i] || '').toUpperCase().replace(/\s+/g, '');
    else if (k === '--pages') a.pages = String(argv[++i] || '').split(',').map((s) => s.trim()).filter(Boolean);
    else if (k === '--timeout') a.timeout = parseInt(argv[++i], 10);
    else if (k === '--since') a.since = String(argv[++i] || '');
    else if (k === '--until') a.until = String(argv[++i] || '');
    else if (k === '--help' || k === '-h') { console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]); process.exit(0); }
    else { console.error(`unknown argument: ${k}`); process.exit(1); }
  }
  if (/^\d{7}$/.test(a.pws || '')) a.pws = 'LA' + a.pws;
  if (!/^LA\d{7}$/.test(a.pws || '')) { console.error('error: --pws LA1234567 is required'); process.exit(1); }
  const bad = a.pages.filter((p) => !PAGES[p]);
  if (bad.length) { console.error(`error: unknown page(s) ${bad.join(', ')}; choose from ${Object.keys(PAGES).join(', ')}`); process.exit(1); }
  if (![a.since, a.until].every((d) => /^\d{4}-\d\d-\d\d$/.test(d)) || a.since > a.until) { console.error('error: --since/--until must be YYYY-MM-DD, since first'); process.exit(1); }
  if (!(a.timeout > 0)) { console.error('error: --timeout must be a positive number of seconds'); process.exit(1); }
  return a;
}

/** The query without paging, so every page of one search lands in the same file. */
function baseQuery(u) {
  const keep = [...u.searchParams.entries()].filter(([k]) => !PAGING.has(k));
  keep.sort((x, y) => (x[0] + x[1]).localeCompare(y[0] + y[1]));
  return new URLSearchParams(keep).toString();
}

function save(pws, widget, u, body, cookies) {
  const q = baseQuery(u);
  const dir = path.join(OUT, pws);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${widget}__${crypto.createHash('sha1').update(q).digest('hex').slice(0, 12)}.json`);
  let rec = { widget, pwsid: pws, query: q, bd: u.searchParams.get('bd'), ed: u.searchParams.get('ed'), pages: {} };
  if (fs.existsSync(file)) {
    try { rec = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* a torn write is replaced below */ }
  }
  const rows = Array.isArray(body) ? body : body.value;
  const count = Array.isArray(body) ? null : body['@odata.count'];
  rec.pages[u.searchParams.get('$skip') || '0'] = rows;
  if (Number.isInteger(count)) rec.count = count;
  rec.captured_at = new Date().toISOString();
  rec.grvalue_cookie = cookies;
  fs.writeFileSync(file + '.part', JSON.stringify(rec));
  fs.renameSync(file + '.part', file);
  const unique = new Map(Object.values(rec.pages).flat().map((r) => [JSON.stringify(r), r]));
  const results = [...unique.values()].reduce((n, r) => n + (Array.isArray(r.Results) ? r.Results.length : 1), 0);
  return { file, have: unique.size, count: rec.count, rows: rows.length, results };
}

const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10);
/** Calendar-year windows covering since..until, newest first so the most recent data lands first. */
function years(since, until) {
  const out = [];
  for (let y = Number(until.slice(0, 4)); y >= Number(since.slice(0, 4)); y--) {
    out.push([since > `${y}-01-01` ? since : `${y}-01-01`, until < `${y}-12-31` ? until : `${y}-12-31`]);
  }
  return out;
}
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const { chromium } = require('playwright');
  const profile = path.join(__dirname, '.pw-profile');
  fs.mkdirSync(profile, { recursive: true });
  const context = await chromium.launchPersistentContext(profile, { headless: false, viewport: { width: 1360, height: 900 } });

  let captured = 0;
  let gatewayBlocked = false;
  let grSeen = null;
  const pending = [];
  const ours = new Set();      // URLs this script requested; fetchPage saves those itself
  const template = {};         // widget -> the last URL the viewer itself loaded successfully
  const waiters = [];
  const challenged = new Set();
  const grCookies = async () => (await context.cookies(LDH)).filter((c) => c.name === 'grValue').map((c) => ({ expires: c.expires }));
  const stopForGateway = async (widget) => {
    gatewayBlocked = true;
    console.error(`\nLDH's gateway refused ${widget} from this IP (HTTP 403). Stopping; nothing will be retried.`);
    console.error('Wait (hours, not minutes) before trying again.');
    await context.close().catch(() => {});
  };

  context.on('response', (resp) => pending.push((async () => {
    const u = new URL(resp.url());
    if (!u.href.startsWith(LDH)) return;
    const sc = (await resp.headerValue('set-cookie').catch(() => null)) || '';
    if (/(^|[\s,;])grValue=/.test(sc)) grSeen = sc.match(/grValue=[^;]*(;[^,]*)?/)[0];
    if (!u.pathname.startsWith('/sdwis/') || ours.has(u.href)) return;
    const widget = u.pathname.slice('/sdwis/'.length);
    const status = resp.status();
    if (status === 403) {
      const text = await resp.text().catch(() => '');
      const gateway = /Application-Gateway/i.test(text);
      // The viewer's own calls (system header, settings) carry no reCAPTCHA token, so a gateway refusal
      // there means this IP is blocked. A grid's 403 may instead be a failed token check, which the
      // person can still clear, so the browser stays open for them.
      if (gateway && !WIDGETS.has(widget)) return stopForGateway(widget);
      if (WIDGETS.has(widget)) {
        challenged.add(widget);
        console.log(`\n>>> [${widget}] reCAPTCHA check not passed (HTTP 403${gateway ? ' from LDH\'s gateway' : ''}). Click "I'm not a robot" in the browser`);
        console.log('>>> (and finish any image challenge Google shows). The capture then continues by itself.');
        console.log('>>> If the page shows an error instead of a checkbox, close the browser and try again later.\n');
      }
      return;
    }
    if (!WIDGETS.has(widget) || status !== 200) return;
    let body;
    try { body = await resp.json(); } catch { return; }
    if (!body || (!Array.isArray(body) && !Array.isArray(body.value))) return;
    // The viewer's own default window is kept too; dww.py merges it with the requested one.
    const r = save(a.pws, widget, u, body, await grCookies());
    captured++;
    template[widget] = u.href;
    challenged.delete(widget);
    for (const w of waiters.splice(0)) { if (w.widget === widget) w.resolve(true); else waiters.push(w); }
    console.log(`[${widget}] viewer's own window ${u.searchParams.get('bd') || '?'} to ${u.searchParams.get('ed') || '?'}: ${r.have}${Number.isInteger(r.count) ? ' of ' + r.count : ''} rows`);
  })().catch((e) => console.error(`capture error: ${e.message}`))));

  // Closing the last window on macOS leaves Chromium running, so the context's own close event never
  // fires; the last tab closing counts as done too.
  const closed = new Promise((res) => {
    context.on('close', res);
    const watch = (pg) => pg.on('close', () => { if (context.pages().length === 0) res(); });
    context.pages().forEach(watch);
    context.on('page', watch);
  });
  const deadline = Date.now() + a.timeout * 1000;

  // Resolves true once the viewer itself has loaded this grid. Waits two minutes, or until the overall
  // deadline while a reCAPTCHA checkbox is waiting for the person.
  const viewerLoaded = (widget) => new Promise((resolve) => {
    const w = { widget, resolve: null };
    const started = Date.now();
    const tick = setInterval(() => {
      const limit = challenged.has(widget) ? deadline : Math.min(deadline, started + 120000);
      if (Date.now() > limit || gatewayBlocked) {
        clearInterval(tick);
        const i = waiters.indexOf(w);
        if (i >= 0) waiters.splice(i, 1);
        resolve(false);
      }
    }, 500);
    w.resolve = (v) => { clearInterval(tick); resolve(v); };
    waiters.push(w);
  });

  const page = context.pages()[0] || (await context.newPage());

  /** Opens the grid so the viewer makes its own call, which is where the checkbox appears if one is needed. */
  async function openGrid(route, tab, widget) {
    delete template[widget];
    const loaded = viewerLoaded(widget);
    await page.goto(`${LDH}${route}?n0=${a.pws}`, { waitUntil: 'networkidle', timeout: 90000 });
    if (tab) await page.locator(tab).click();
    // Most grids load on their own; Chemical Samples waits for Search.
    const quick = await Promise.race([loaded, sleep(6000).then(() => null)]);
    if (quick === null) {
      const search = page.locator('button.btn-primary:visible', { hasText: 'Search' }).first();
      if (await search.count()) await search.click().catch(() => {});
      return loaded;
    }
    return quick;
  }

  /** One page of a grid, requested from inside the viewer's page with the header the viewer itself sends. */
  async function fetchPage(widget, bd, ed, skip) {
    const u = new URL(template[widget]);
    u.searchParams.set('bd', bd);
    u.searchParams.set('ed', ed);
    u.searchParams.set('$skip', String(skip));
    u.searchParams.set('$top', String(TOP[widget] || 1000));
    u.searchParams.set('$count', 'true');
    ours.add(u.href);
    const res = await page.evaluate(async (href) => {
      const xsrf = (document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]*)/) || [])[1];
      const headers = { Accept: 'application/json' };
      if (xsrf) headers['X-XSRF-TOKEN'] = decodeURIComponent(xsrf);
      const r = await fetch(href, { credentials: 'same-origin', headers });
      return { status: r.status, text: await r.text() };
    }, u.href);
    if (res.status !== 200) return { status: res.status, gateway: /Application-Gateway/i.test(res.text) };
    let body;
    try { body = JSON.parse(res.text); } catch { return { status: 'empty' }; }
    if (!body || !Array.isArray(body.value)) return { status: 'shape' };
    const r = save(a.pws, widget, u, body, await grCookies());
    captured++;
    return { status: 200, ...r };
  }

  /**
   * Every row of one date window. The viewer stops at 1,000 rows per search, so a window with more is asked
   * for again as shorter windows, each saved as its own search.
   */
  async function fetchWindow(job, bd, ed, reopened = false) {
    const [route, tab, widget, label] = job;
    let skip = 0;
    let count = null;
    let results = 0;
    for (;;) {
      if (gatewayBlocked) return [];
      const r = await fetchPage(widget, bd, ed, skip);
      if (r.status === 403) {
        if (r.gateway) { await stopForGateway(widget); return []; }
        // The 20-minute pass ran out. Reopen the page so the viewer runs its own check and the person can
        // click the checkbox; after one fresh pass a second refusal ends this window.
        if (reopened) return [`${label} ${bd} to ${ed}: refused again right after a fresh pass`];
        console.log(`[${widget}] the reCAPTCHA pass has ended; reopening the page for a new check`);
        if (!(await openGrid(route, tab, widget))) return [`${label} ${bd} to ${ed}: the viewer did not load the grid again`];
        return fetchWindow(job, bd, ed, true);
      }
      if (r.status !== 200) return [`${label} ${bd} to ${ed}: ${r.status === 'empty' ? 'empty or non-JSON answer' : r.status === 'shape' ? 'unexpected answer shape' : 'HTTP ' + r.status}`];
      if (Number.isInteger(r.count)) count = r.count;
      console.log(`[${widget}] ${bd} to ${ed}: ${r.have}${count === null ? '' : ' of ' + count} rows saved`);
      if (r.results >= RESULT_CAP) { results = r.results; break; }
      if (count === null || r.have >= count) return [];
      if (r.rows === 0 || skip + 2 * r.rows > REACH) break;
      skip += r.rows;
      await sleep(GAP);
    }
    const b = Date.parse(bd), e = Date.parse(ed);
    const days = Math.round((e - b) / DAY) + 1;
    if (days < 2) return [`${label} ${bd}: more rows in a single day than one search returns; cannot split further`];
    // Targets below the limits leave room for uneven sampling; a window still too full splits again.
    const parts = Math.min(days, Math.max(2, Math.ceil((count || 0) / 800), Math.ceil(results / 3500)));
    console.log(`[${widget}] ${bd} to ${ed}: ${results >= RESULT_CAP ? 'near LDH\'s 5,000-result limit' : count + ' rows is more than the viewer pages through'}; asking for ${parts} shorter windows`);
    const problems = [];
    for (let i = 0; i < parts && !gatewayBlocked; i++) {
      const pb = isoDay(b + Math.floor((days * i) / parts) * DAY);
      const pe = isoDay(b + (Math.floor((days * (i + 1)) / parts) - 1) * DAY);
      await sleep(GAP);
      problems.push(...await fetchWindow(job, pb, pe));
    }
    return problems;
  }

  console.log(`${a.pws}: capturing ${a.since} to ${a.until} on ${a.pages.join(', ')}.`);
  console.log('A browser window opens and does the work itself. You may have nothing to do.');
  console.log('If it shows "I\'m not a robot", click it; that is the only step that needs you.\n');
  // A deep link in a fresh profile fails: the system lookup it triggers returns HTTP 500 until the home
  // page has set the anti-forgery cookies, and the viewer then drops back to its home page.
  await page.goto(LDH, { waitUntil: 'networkidle', timeout: 90000 }).catch((e) => console.error(`home page: ${e.message}`));
  const problems = [];
  for (const p of a.pages) {
    for (const job of JOBS[p]) {
      if (gatewayBlocked) break;
      const label = job[3];
      try {
        if (!(await openGrid(job[0], job[1], job[2]))) { problems.push(`${label}: the viewer did not load the grid`); continue; }
        for (const [bd, ed] of job[4] ? years(a.since, a.until) : [[a.since, a.until]]) {
          if (gatewayBlocked) break;
          await sleep(GAP);
          problems.push(...await fetchWindow(job, bd, ed));
        }
      } catch (e) {
        problems.push(`${label}: ${e.message.split('\n')[0]}`);
      }
    }
  }
  if (problems.length && !gatewayBlocked) {
    console.log('\nNot finished automatically:');
    for (const x of problems) console.log(`  ${x}`);
    console.log('The browser stays open: finish those searches by hand (set the dates, press Search, page through),');
    console.log(`then close the browser. Waiting up to ${Math.max(0, Math.round((deadline - Date.now()) / 1000))}s.`);
    await Promise.race([closed, sleep(Math.max(0, deadline - Date.now()))]);
  }
  await Promise.allSettled(pending);
  await context.close().catch(() => {});

  if (grSeen) console.log(`LDH set a grValue cookie (${grSeen.replace(/grValue=[^;]*/, 'grValue=<value>')}).`);
  console.log(captured ? `Done: ${captured} grid responses saved under ${path.join(OUT, a.pws)}` : 'Nothing captured.');
  process.exit(gatewayBlocked ? 5 : !captured ? 4 : problems.length ? 3 : 0);
}

main().catch((e) => { console.error(`error: ${e.message}`); process.exit(1); });
