#!/usr/bin/env node
/**
 * ldeq-edms-download harness — local use only.
 *
 * Drives a real (headful) Chromium through the LDEQ EDMS UI to search,
 * select, and download documents. The download popup always shows a
 * classic reCAPTCHA v2 "I'm not a robot" checkbox (confirmed by reading
 * main.9fa4b2ed48b5f935.js: ngx-recaptcha2's `success` handler sets the
 * token and immediately calls createDownloadRequest() — no separate
 * submit button). This script cannot and does not solve that CAPTCHA;
 * it opens a visible window and waits for a human to click it.
 *
 * Usage:
 *   node edms_download.js --ai 26336 --out ~/Downloads/edms-26336
 *   node edms_download.js --ai 26336 --doc 15257395 --doc 15257366 --out ./out
 *   node edms_download.js --ai 26336 --all --out ./out
 *
 * The EDMS "Download selected documents" button caps selection at 20
 * documents per click, so requests are split into batches of 20 — each
 * batch opens its own popup and requires its own CAPTCHA solve.
 */

const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require('playwright');

const BASE = 'https://edms.deq.louisiana.gov/edmsv2';
const BATCH_SIZE = 20; // hard site limit ("Max 20 selected")
const MAX_PAGES_TO_SCAN = 20; // safety cap when hunting for --doc ids across result pages

function parseArgs(argv) {
  const args = { doc: [], out: null, ai: null, all: false, timeout: 3600 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--ai') args.ai = argv[++i];
    else if (a === '--doc') args.doc.push(String(argv[++i]));
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--all') args.all = true;
    else if (a === '--timeout') args.timeout = parseInt(argv[++i], 10);
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else { console.error(`Unknown argument: ${a}`); printHelp(); process.exit(1); }
  }
  if (!args.ai) { console.error('error: --ai <AI number> is required'); process.exit(1); }
  if (!args.all && args.doc.length === 0) {
    console.error('error: pass --all to download every result, or one or more --doc <id>');
    process.exit(1);
  }
  if (!args.out) {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    args.out = path.join(os.homedir(), 'Downloads', `edms-${args.ai}-${stamp}`);
  }
  return args;
}

function printHelp() {
  console.log(`
ldeq-edms-download — download real files from LDEQ EDMS via a headful browser

  --ai <number>       AI (Agency Interest) number to search (required)
  --doc <id>          Document ID to download (the plain numeric "Document ID"
                       column, e.g. 15257395). Repeatable.
  --all               Download every result on the first results page
                       (up to 100 docs, batched 20 at a time — one CAPTCHA
                       solve per batch of 20).
  --out <dir>         Output directory (default: ~/Downloads/edms-<AI>-<ts>)
  --timeout <seconds> Max seconds to wait per batch for the CAPTCHA to be
                       solved and the download to complete (default: 300)

A visible Chrome window will open. EDMS shows a classic "I'm not a robot"
checkbox for every download batch — click it (and solve any image challenge
Google shows) in that window; the download starts automatically afterward.
`);
}

async function searchByAi(page, ai) {
  await page.goto(`${BASE}/quick-search`, { waitUntil: 'networkidle', timeout: 60000 });
  await page.fill('#aiNumbers', String(ai));
  await page.click('#search');
  await page.waitForSelector('tr.k-master-row', { timeout: 30000 });
  await page.waitForTimeout(500);
}

async function readGridRows(page) {
  // Row N and "Select Row" checkbox N are aligned 1:1 in DOM order (verified
  // against the live grid: both selectors return the same count and the
  // first checkbox toggles the first row).
  return page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
    return rows.map((row, i) => {
      const cells = Array.from(row.querySelectorAll('td')).map((td) => td.innerText.trim());
      return { index: i, docId: cells[1] || null };
    });
  });
}

async function goToNextPage(page) {
  const next = await page.$('[title="Go to the next page"]');
  if (!next) return false;
  const disabled = await next.evaluate((el) => el.classList.contains('k-disabled'));
  if (disabled) return false;
  await next.click();
  await page.waitForTimeout(1500);
  return true;
}

/** Find grid row indices (on whichever page they end up on) matching requested docIds. */
async function locateRowsForDocIds(page, docIds) {
  const remaining = new Set(docIds.map(String));
  const found = []; // { docId, index } — index is only valid for the page it was found on
  let pageNum = 1;
  while (remaining.size > 0 && pageNum <= MAX_PAGES_TO_SCAN) {
    const rows = await readGridRows(page);
    for (const row of rows) {
      if (row.docId && remaining.has(row.docId)) {
        found.push({ docId: row.docId, index: row.index });
        remaining.delete(row.docId);
      }
    }
    if (remaining.size === 0) break;
    const advanced = await goToNextPage(page);
    if (!advanced) break;
    pageNum++;
  }
  if (remaining.size > 0) {
    console.error(`warning: could not find these document IDs in the search results: ${[...remaining].join(', ')}`);
  }
  return found; // NOTE: caller must select+download these while still on the page they were found on
}

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

async function selectRowsByIndex(page, indices) {
  const checkboxes = await page.$$('input[type="checkbox"][aria-label="Select Row"]');
  for (const idx of indices) {
    if (idx >= checkboxes.length) continue;
    await checkboxes[idx].click();
  }
}

/**
 * Click the download button, wait for the popup, walk the user through the CAPTCHA, capture the file.
 *
 * After the CAPTCHA is solved, EDMS does NOT auto-trigger a browser download event — it takes an
 * unpredictable amount of time (confirmed: minutes, growing with document count/size) to gather and
 * zip the requested documents server-side, then swaps in the text "Document has been processed." and
 * reveals `<a id="download-link" href="https://edms.deq.louisiana.gov/app/cache/<uuid>.zip">` (an SVG
 * icon, no text — a `:has-text("Download")` selector will never match it). Confirmed against a live
 * single-doc test (docid 31003500330030003800340035003700): once `#download-link` has a non-empty
 * href, fetching that href with `context.request.get()` (reusing the browser context's cookies) works
 * directly — status 200, valid zip — with no need to click the link or wait for a `download` event at
 * all. This avoids the popup's own click/navigation entirely and is more reliable than relying on
 * Playwright's `download` event, which this endpoint never fires.
 */
async function runDownloadBatch(context, page, outDir, batchLabel, timeoutSeconds) {
  const downloadBtn = await page.$('[title*="Download selected documents"]');
  if (!downloadBtn) throw new Error('Download button not found — selectors may be stale (EDMS UI changed).');

  console.log(`\n[${batchLabel}] opening download window...`);
  const [popup] = await Promise.all([
    context.waitForEvent('page'),
    downloadBtn.click(),
  ]);
  await popup.waitForLoadState('domcontentloaded').catch(() => {});

  let popupClosed = false;
  popup.on('close', () => { popupClosed = true; });

  console.log(`[${batchLabel}] >>> A Chrome window is open. Click the "I'm not a robot" checkbox`);
  console.log(`[${batchLabel}] >>> (and solve any image challenge Google shows) to continue.`);
  console.log(`[${batchLabel}] Waiting up to ${timeoutSeconds}s for the CAPTCHA solve + server-side`);
  console.log(`[${batchLabel}] file assembly (large batches can take several minutes after the CAPTCHA)...`);

  const deadline = Date.now() + timeoutSeconds * 1000;
  let href = null;
  while (Date.now() < deadline && !popupClosed) {
    const link = await popup.$('#download-link').catch(() => null);
    if (link) {
      const visible = await link.isVisible().catch(() => false);
      if (visible) {
        href = await link.getAttribute('href').catch(() => null);
        if (href) break;
      }
    }
    await new Promise((r) => setTimeout(r, 1500));
  }

  if (!href) {
    if (popupClosed) {
      throw new Error(`[${batchLabel}] the download window was closed before the file was ready — batch cancelled.`);
    }
    throw new Error(`[${batchLabel}] timed out after ${timeoutSeconds}s waiting for the CAPTCHA to be solved / file to be ready. Re-run with --timeout <n> to allow more time.`);
  }

  console.log(`[${batchLabel}] file ready, fetching ${href}`);
  const resp = await context.request.get(href);
  if (!resp.ok()) {
    throw new Error(`[${batchLabel}] fetching ${href} returned HTTP ${resp.status()}`);
  }
  const buf = await resp.body();

  fs.mkdirSync(outDir, { recursive: true });
  const suggested = path.basename(new URL(href).pathname) || `edms-${batchLabel}.zip`;
  const dest = path.join(outDir, suggested);
  fs.writeFileSync(dest, buf);
  console.log(`[${batchLabel}] saved -> ${dest}`);

  await popup.close().catch(() => {});
  return dest;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const profileDir = path.join(__dirname, '.pw-profile');
  fs.mkdirSync(profileDir, { recursive: true });

  const context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    acceptDownloads: true,
    viewport: { width: 1280, height: 900 },
  });
  const page = context.pages()[0] || (await context.newPage());

  const saved = [];
  try {
    console.log(`Searching AI ${args.ai}...`);
    await searchByAi(page, args.ai);

    let batches; // array of { indices: number[] } to run, one page-position at a time
    if (args.doc.length > 0) {
      const located = await locateRowsForDocIds(page, args.doc);
      if (located.length === 0) throw new Error('None of the requested --doc IDs were found in the search results.');
      batches = chunk(located, BATCH_SIZE).map((group) => group.map((g) => g.index));
    } else {
      // --all: current (first) results page only, batched by 20.
      const rows = await readGridRows(page);
      if (rows.length === 0) throw new Error('No search results found for this AI number.');
      console.log(`Found ${rows.length} document(s) on the results page. Downloading in batches of ${BATCH_SIZE}.`);
      batches = chunk(rows.map((r) => r.index), BATCH_SIZE);
    }

    for (let i = 0; i < batches.length; i++) {
      const label = `batch ${i + 1}/${batches.length}`;
      // Selections reset per navigation; if we paginated while locating --doc
      // rows, we're already sitting on the correct page for those indices.
      await selectRowsByIndex(page, batches[i]);
      const dest = await runDownloadBatch(context, page, args.out, label, args.timeout);
      saved.push(dest);
    }
  } finally {
    await context.close().catch(() => {});
  }

  console.log('\nDone. Saved files:');
  for (const f of saved) console.log(f);
}

main().catch((e) => {
  console.error(`\nerror: ${e.message}`);
  process.exit(1);
});
