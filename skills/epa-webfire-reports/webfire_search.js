#!/usr/bin/env node
/**
 * epa-webfire-reports harness — search and download CEDRI reports published in EPA WebFIRE.
 *
 * WebFIRE's report search is a three-page ColdFusion flow:
 *   esearch.cfm       pick report type(s)            -> POST esearch2.cfm
 *   esearch2.cfm      criteria form (#searchform)     -> POST eSearchResults.cfm
 *   eSearchResults.cfm results table with document links
 *
 * The step-2 selects live inside collapsed jQuery-UI accordions behind jquery.multiselect, and
 * `county` / `CFRSubpart` are filled by ColdFusion AJAX binds that do not fire reliably under
 * automation, so values are written straight into the underlying <select> elements. The form has
 * to be submitted by clicking its submit button: the server expects `Submit=Submit+Search` and a
 * bare form.submit() bounces back to the start page.
 *
 * When the application fails, WebFIRE answers HTTP 200 (sometimes 500) with a "Resource Not Found"
 * page, so page titles are checked rather than status codes.
 *
 * Usage:
 *   node webfire_search.js --health
 *   node webfire_search.js --list-subparts --part "Part 63"
 *   node webfire_search.js --type AER --state LA --facility "NORCO CHEMICAL PLANT" --part "Part 63" \
 *       --subpart "Subpart YY" --subpart "Subpart XX" --from 01/01/2024 --to 12/31/2026 \
 *       --out ./webfire-out [--download]
 */

const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const { chromium } = require('playwright');

const BASE = 'https://cfpub.epa.gov/webfire/reports';
const CFC = `${BASE}/comp/countyAutoSelectComp.cfc`;
const TYPES = { All: 'All', AER: 'AER', ST: 'ST', NOCS: 'NOCS' };
const EXIT_SERVER_DOWN = 3;

function parseArgs(argv) {
  const a = {
    type: [], state: [], county: [], frs: [], part: [], subpart: [],
    org: '', facility: '', city: '', zip: '', from: '', to: '',
    out: null, download: false, health: false, listSubparts: false,
    headful: false, timeout: 600,
  };
  const multi = { '--type': 'type', '--state': 'state', '--county': 'county', '--frs': 'frs', '--part': 'part', '--subpart': 'subpart' };
  const single = { '--org': 'org', '--facility': 'facility', '--city': 'city', '--zip': 'zip', '--from': 'from', '--to': 'to', '--out': 'out' };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (multi[k]) a[multi[k]].push(argv[++i]);
    else if (single[k]) a[single[k]] = argv[++i];
    else if (k === '--download') a.download = true;
    else if (k === '--health') a.health = true;
    else if (k === '--list-subparts') a.listSubparts = true;
    else if (k === '--timeout') a.timeout = parseInt(argv[++i], 10);
    else if (k === '--headful') a.headful = true;
    else if (k === '--help' || k === '-h') { printHelp(); process.exit(0); }
    else { console.error(`Unknown argument: ${k}`); printHelp(); process.exit(1); }
  }
  if (a.type.length === 0) a.type = ['AER'];
  for (const t of a.type) if (!TYPES[t]) { console.error(`--type must be one of ${Object.keys(TYPES).join(', ')}`); process.exit(1); }
  for (const d of [a.from, a.to]) if (d && !/^\d{2}\/\d{2}\/\d{4}$/.test(d)) { console.error(`dates must be MM/DD/YYYY, got ${d}`); process.exit(1); }
  if (a.subpart.length && a.part.length === 0) { console.error('--subpart needs --part (e.g. --part "Part 63")'); process.exit(1); }
  if (!a.out) a.out = path.join(os.homedir(), 'Downloads', `webfire-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  return a;
}

function printHelp() {
  console.log(`
epa-webfire-reports — search/download CEDRI reports (AERs, performance tests, NOCS) from EPA WebFIRE

  --health                 check the search form, the subpart lookup, and a trivial search; exit 3 if down
  --list-subparts          print CFRSubpart values for --part (default "Part 63")
  --type AER|ST|NOCS|All   report type (repeatable; default AER = periodic/compliance/excess-emissions reports)
  --state LA               state code (repeatable)
  --county "ST. CHARLES"   county text as filed, exact match (repeatable; spellings vary, prefer --facility)
  --city, --zip            facility location
  --org, --facility        submitting organization / facility name (free text)
  --frs <id>               FRS registry ID (repeatable)
  --part "Part 63"         "Part 60" | "Part 62" | "Part 63" (repeatable)
  --subpart "Subpart YY"   exact value from --list-subparts (repeatable)
  --from, --to MM/DD/YYYY  CEDRI submission-date window
  --out <dir>              output directory (default ~/Downloads/webfire-<stamp>)
  --download               also fetch every document linked from the results
  --timeout <s>            per-navigation timeout in seconds (default 600)
  --headful                show the browser
`);
}

function csvCell(v) {
  const s = v == null ? '' : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function writeCsv(file, header, rows) {
  fs.writeFileSync(file, [header, ...rows].map(r => r.map(csvCell).join(',')).join('\n') + '\n');
}

async function isErrorPage(page) {
  const title = await page.title();
  return /Resource Not Found/i.test(title);
}

async function fetchSubparts(request, part) {
  const url = `${CFC}?method=getCFRSubpart&returnFormat=json&argumentCollection=${encodeURIComponent(JSON.stringify({ CFRpart: part }))}`;
  const r = await request.get(url);
  if (!r.ok()) throw new Error(`subpart lookup HTTP ${r.status()}`);
  const j = await r.json();
  return j.DATA.map(([value, title]) => ({ value, title }));
}

async function openCriteriaForm(page, types, timeoutMs) {
  await page.goto(`${BASE}/esearch.cfm`, { waitUntil: 'networkidle', timeout: timeoutMs });
  if (await isErrorPage(page)) throw Object.assign(new Error('esearch.cfm returned the EPA error page'), { down: true });
  await page.selectOption('#reporttype', types);
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle', timeout: timeoutMs }), page.click('#Submit')]);
  if (await isErrorPage(page)) throw Object.assign(new Error('esearch2.cfm returned the EPA error page'), { down: true });
}

async function fillAndSubmit(page, a, timeoutMs) {
  await page.evaluate((a) => {
    const pick = (id, values, inject) => {
      const sel = document.querySelector(id);
      if (!sel || values.length === 0) return;
      if (inject) sel.innerHTML = '';
      const have = new Set([...sel.options].map(o => o.value));
      for (const v of values) if (!have.has(v)) sel.add(new Option(v, v));
      for (const o of sel.options) o.selected = values.includes(o.value);
    };
    pick('#state', a.state, false);
    pick('#county', a.county, true);
    pick('#frs', a.frs, false);
    pick('#CFRpart', a.part, false);
    pick('#CFRSubpart', a.subpart, true);
    for (const k of ['organization', 'facility', 'city', 'zip', 'startdate', 'enddate']) {
      const el = document.querySelector(`#${k}`) || document.querySelector(`[name=${k}]`);
      const v = { organization: a.org, facility: a.facility, city: a.city, zip: a.zip, startdate: a.from, enddate: a.to }[k];
      if (el) el.value = v || '';
    }
  }, a);
  let body = null;
  const onReq = r => { if (r.url().includes('eSearchResults')) body = r.postData(); };
  page.on('request', onReq);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle', timeout: timeoutMs }),
    page.evaluate(() => document.querySelector('#searchform input[type=submit]').click()),
  ]);
  page.off('request', onReq);
  return body;
}

// eSearchResults.cfm sends every matching row in one response, then DataTables (#myDocTable)
// pages them client-side and detaches all but the first page from the DOM, so rows are read
// through the DataTables API. The page loads several jQuery copies; only some of them hold the
// table's DataTables instance, so each global is tried. textContent is used because innerText is
// empty on detached rows.
async function scrapeResults(page) {
  return page.evaluate(() => {
    const clean = s => s.replace(/\s+/g, ' ').trim();
    const m = document.documentElement.innerHTML.match(/shows the\s*(?:<b>)?\s*([\d,]+)\s*(?:<\/b>)?\s*records/);
    const total = m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
    const t = document.querySelector('#myDocTable');
    if (!t) return { header: [], rows: [], total };
    // Header cells break lines with <br>, which textContent drops ("Report<br>Type" -> "ReportType").
    const header = [...t.querySelectorAll('thead tr:first-child th')].map(c => clean(c.innerText));
    const jq = [window.$, window.jQuery].find(j => j && j.fn && j.fn.dataTable && j.fn.dataTable.isDataTable(t));
    const dt = jq ? jq(t).DataTable() : null;
    const trs = dt ? dt.rows().nodes().toArray() : [...t.tBodies[0].rows];
    const rows = trs.filter(r => r.cells.length > 1).map(r => ({
      cells: [...r.cells].map(c => clean(c.textContent)),
      links: [...r.querySelectorAll('a[href]')].map(a => a.href).filter(h => !/^javascript:|#$/.test(h)),
      onclick: [...r.querySelectorAll('[onclick]')].map(e => e.getAttribute('onclick')),
    }));
    return { header, rows, total };
  });
}

// CEDRI file names often run past 120 characters; keep the extension so zips and PDFs stay
// recognizable after truncation.
function safeName(s) {
  const clean = s.replace(/[^A-Za-z0-9._-]+/g, '_');
  const ext = (clean.match(/\.[A-Za-z0-9]{1,5}$/) || [''])[0];
  return clean.length <= 120 ? clean : clean.slice(0, 120 - ext.length) + ext;
}

async function downloadAll(context, results, outDir) {
  const filesDir = path.join(outDir, 'files');
  fs.mkdirSync(filesDir, { recursive: true });
  const manifest = [];
  for (const r of results) {
    for (const [j, url] of r.links.entries()) {
      const resp = await context.request.get(url, { timeout: 0 });
      const ctype = resp.headers()['content-type'] || '';
      const body = await resp.body();
      if (!resp.ok() || body.length === 0 || (/text\/html/i.test(ctype) && /Resource Not Found/i.test(body.toString('utf8', 0, 20000)))) {
        throw new Error(`row ${r.row} link ${j}: HTTP ${resp.status()}, ${body.length} bytes, ${ctype} — ${url}`);
      }
      const cd = resp.headers()['content-disposition'] || '';
      const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      const base = safeName(m ? decodeURIComponent(m[1]) : path.basename(new URL(url).pathname) || `link${j}`);
      const file = path.join(filesDir, `row${String(r.row).padStart(4, '0')}-${j}-${base}`);
      fs.writeFileSync(file, body);
      const sha = crypto.createHash('sha256').update(body).digest('hex');
      manifest.push([r.row, j, url, path.relative(outDir, file), body.length, ctype, sha]);
      console.log(`  row ${r.row}: ${path.basename(file)} (${body.length} bytes)`);
    }
  }
  writeCsv(path.join(outDir, 'webfire_DOWNLOADS.csv'), ['row', 'link_index', 'url', 'file', 'bytes', 'content_type', 'sha256'], manifest);
  return manifest.length;
}

async function health(context, timeoutMs) {
  const page = await context.newPage();
  const status = {};
  try {
    await page.goto(`${BASE}/esearch.cfm`, { waitUntil: 'networkidle', timeout: timeoutMs });
    status.search_form = (await isErrorPage(page)) ? 'DOWN' : 'OK';
  } catch (e) { status.search_form = `DOWN (${e.message})`; }
  try {
    const subs = await fetchSubparts(context.request, 'Part 63');
    status.subpart_lookup = subs.length > 1 ? `OK (${subs.length} Part 63 subparts)` : 'DOWN (empty)';
  } catch (e) { status.subpart_lookup = `DOWN (${e.message})`; }
  try {
    await openCriteriaForm(page, ['NOCS'], timeoutMs);
    await fillAndSubmit(page, { state: [], county: [], frs: [], part: [], subpart: [], org: '', facility: '', city: '', zip: '', from: '', to: '' }, timeoutMs);
    status.results = (await isErrorPage(page)) ? 'DOWN (eSearchResults.cfm returns the EPA error page)' : 'OK';
  } catch (e) { status.results = `DOWN (${e.message})`; }
  for (const [k, v] of Object.entries(status)) console.log(`${k.padEnd(15)} ${v}`);
  return Object.values(status).every(v => v.startsWith('OK'));
}

(async () => {
  const a = parseArgs(process.argv.slice(2));
  const timeoutMs = a.timeout * 1000;
  const browser = await chromium.launch({ headless: !a.headful });
  const context = await browser.newContext();
  let code = 0;
  try {
    if (a.health) {
      code = (await health(context, timeoutMs)) ? 0 : EXIT_SERVER_DOWN;
      return;
    }
    if (a.listSubparts) {
      for (const part of a.part.length ? a.part : ['Part 63']) {
        for (const s of await fetchSubparts(context.request, part)) console.log(`${part}\t${s.value}\t${s.title}`);
      }
      return;
    }

    fs.mkdirSync(a.out, { recursive: true });
    const page = await context.newPage();
    await openCriteriaForm(page, a.type, timeoutMs);
    const posted = await fillAndSubmit(page, a, timeoutMs);
    console.log(`POST eSearchResults.cfm: ${posted}`);
    if (await isErrorPage(page)) {
      fs.writeFileSync(path.join(a.out, 'error-page.html'), await page.content());
      throw Object.assign(new Error('eSearchResults.cfm returned the EPA error page (server-side failure; run --health, retry later)'), { down: true });
    }

    fs.writeFileSync(path.join(a.out, 'results-page1.html'), await page.content());
    const { header, rows, total } = await scrapeResults(page);
    const all = rows.map((r, i) => ({ row: i + 1, page: 1, ...r }));
    console.log(`WebFIRE reports ${total ?? '?'} matching records; parsed ${all.length} rows`);
    if (total == null) throw new Error('could not read the record count from the results page (see results-page1.html)');
    if (total !== all.length) {
      throw new Error(`parsed ${all.length} rows but WebFIRE reports ${total}; the results layout may have changed (see results-page1.html)`);
    }

    const width = Math.max(header.length, ...all.map(r => r.cells.length), 0);
    const cols = Array.from({ length: width }, (_, i) => header[i] || `col${i + 1}`);
    writeCsv(path.join(a.out, 'webfire_INDEX.csv'),
      ['row', 'results_page', ...cols, 'links', 'onclick'],
      all.map(r => [r.row, r.page, ...Array.from({ length: width }, (_, i) => r.cells[i] || ''), r.links.join(' '), r.onclick.join(' | ')]));
    console.log(`${all.length} result rows -> ${path.join(a.out, 'webfire_INDEX.csv')}`);

    if (a.download && all.length) {
      const noLinks = all.filter(r => r.links.length === 0);
      if (noLinks.length) console.log(`warning: ${noLinks.length} rows have no plain href (see onclick column); those are not downloaded`);
      const n = await downloadAll(context, all, a.out);
      console.log(`${n} files -> ${path.join(a.out, 'files')} (manifest: webfire_DOWNLOADS.csv)`);
    }
  } catch (e) {
    console.error(`error: ${e.message}`);
    code = e.down ? EXIT_SERVER_DOWN : 1;
  } finally {
    await browser.close();
    process.exit(code);
  }
})();
