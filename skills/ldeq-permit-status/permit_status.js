// Headless Playwright driver for LDEQ's "Check Permit Status" DNN/OWS module.
// No CAPTCHA on this page (unlike EDMS download), so this runs headless and non-interactively.
const { chromium } = require('playwright');

function parseArgs(argv) {
  const out = { ai: null, coname: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--ai') out.ai = argv[++i];
    else if (argv[i] === '--coname') out.coname = argv[++i];
  }
  return out;
}

(async () => {
  const { ai, coname } = parseArgs(process.argv.slice(2));
  if (!ai && !coname) {
    console.error('Usage: node permit_status.js --ai <AI number> | --coname <partial name>');
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('https://internet.deq.louisiana.gov/portal/ONLINESERVICES/CHECK-PERMIT-STATUS', { waitUntil: 'networkidle' });

  if (ai) await page.fill('#txtFlt_AI', ai);
  if (coname) await page.fill('#txtFlt_CoName', coname);
  await page.click('#tbiFilter');
  await page.waitForTimeout(4000);

  const rows = await page.evaluate(() => {
    // The results grid is the DNN/OWS module's <table class="simple">; module container
    // IDs (e.g. lxT489) are assigned per-deployment and not stable, so match on class + header text instead.
    const tables = Array.from(document.querySelectorAll('table.simple'));
    const table = tables.find(t => t.querySelector('th') && t.innerText.includes('AI Name'));
    if (!table) return null;
    const trs = Array.from(table.querySelectorAll('tr'));
    return trs.map(tr => Array.from(tr.querySelectorAll('th,td')).map(c => c.textContent.trim()));
  });

  await browser.close();

  if (!rows || rows.length <= 1) {
    console.log(JSON.stringify({ count: 0, rows: [] }));
    return;
  }

  const header = rows[0];
  const records = rows.slice(1).map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
  console.log(JSON.stringify({ count: records.length, header, records }, null, 2));
})();
