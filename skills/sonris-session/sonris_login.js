#!/usr/bin/env node
/**
 * sonris_login.js — logs into a *registered* SONRIS account inside a real
 * stealth browser session, optionally following up with one authenticated
 * page fetch in the same session.
 *
 * This is a different tier from sonris_session.js. That script captures the
 * anonymous CAPTCHA-passed cookie every sonris-* skill needs just to get
 * past the edge gate — it never authenticates as anyone. Some SONRIS pages
 * (e.g. the CUP "comments"/tracking view at f?p=129:560) go a step further
 * and redirect an anonymous-but-CAPTCHA-passed session to a login form
 * (P101_USERNAME / P101_PASSWORD, submitted via apex.submit({request:
 * 'LOGIN'})). This script drives that form for a registered account.
 *
 * Session-ID handling: Oracle APEX embeds a numeric session/instance ID in
 * every URL (f?p=<app>:<page>:<instance>:...). That ID is minted fresh on
 * login and isn't known in advance, so a --then-url can't hardcode one.
 * Pass the literal token SESSION where the instance ID would go and this
 * script substitutes the real post-login instance ID it lands on, e.g.:
 *   f?p=129:560:SESSION:::0:P560_CUP_NUM:P20260152
 *
 * The resulting authenticated cookies are saved to .session/auth_profile.json
 * — separate from .session/profile.json (the anonymous capture every other
 * sonris-* skill shares) so logging in here never overwrites that.
 *
 * Usage:
 *   node sonris_login.js --username <u> --password <p> [--then-url <url>] [--headless] [--timeout 60]
 *
 * Exit codes: 0 ok, 1 script error, 2 login failed (bad creds, or the form
 * changed shape and the selectors below no longer match).
 */

const fs = require('fs');
const path = require('path');

const sessionProfile = require('./lib/session_profile');
const stealth = require('./lib/stealth');

const LOGIN_URL = 'https://sonlite.dnr.state.la.us/ords/f?p=129:101';
const AUTH_PROFILE_FILE = path.join(__dirname, '.session', 'auth_profile.json');
const INSTANCE_RE = /f\?p=\d+:\d+:(\d+):/;

function parseArgs(argv) {
  const args = { username: null, password: null, thenUrl: null, headless: false, timeout: 60 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--username') args.username = argv[++i];
    else if (a === '--password') args.password = argv[++i];
    else if (a === '--then-url') args.thenUrl = argv[++i];
    else if (a === '--headless') args.headless = true;
    else if (a === '--timeout') args.timeout = parseInt(argv[++i], 10);
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
sonris_login.js — log into a registered SONRIS account, optionally fetch one
authenticated page after

  --username <u>    SONRIS account username (required)
  --password <p>    SONRIS account password (required)
  --then-url <url>  After login, navigate here in the same authenticated
                     session and print {url,finalUrl,status,body} as JSON.
                     Use the literal token SESSION where the instance ID
                     goes — it's substituted with the real post-login one.
  --headless        Run without a visible window (default: visible, same as
                     the browser transport in lib/transports.js).
  --timeout <sec>   Max seconds to wait per step (default: 60).

Exit codes: 0 ok, 1 script error, 2 login failed.
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.username || !args.password) {
    console.error('error: --username and --password are required');
    printHelp();
    process.exit(1);
  }

  const { chromium } = require('playwright');
  const profileDir = path.join(__dirname, '.pw-profile');
  fs.mkdirSync(profileDir, { recursive: true });

  const loaded = sessionProfile.loadProfile();
  const context = await stealth.launchStealthContext(chromium, profileDir, {
    acceptDownloads: true,
    headless: args.headless,
  });

  try {
    if (loaded && loaded.profile.cookies) {
      const cookies = Object.entries(loaded.profile.cookies).map(([name, value]) => ({
        name,
        value,
        domain: 'sonlite.dnr.state.la.us',
        path: '/',
      }));
      await context.addCookies(cookies);
    }

    const page = context.pages()[0] || (await context.newPage());
    console.log('Navigating to login page...');
    await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: args.timeout * 1000 });

    if (/SHOW_CAPTCHA/i.test(page.url())) {
      console.error(
        'error: redirected to the CAPTCHA gate before reaching the login form — the anonymous session needs a fresh capture first (run sonris_session.js).'
      );
      process.exit(2);
      return;
    }

    const userField = page.locator('#P101_USERNAME');
    const passField = page.locator('#P101_PASSWORD');
    await userField.waitFor({ state: 'visible', timeout: args.timeout * 1000 });
    await userField.fill(args.username);
    await passField.fill(args.password);

    console.log('Submitting login form...');
    const navPromise = page
      .waitForNavigation({ waitUntil: 'domcontentloaded', timeout: args.timeout * 1000 })
      .catch(() => null);
    await page.getByRole('button', { name: 'Log In' }).click();
    await navPromise;
    // A bad-credentials response sometimes reloads the same page with an
    // inline error region instead of a real navigation — give it a beat.
    await page.waitForTimeout(1500);

    const stillOnLoginForm = await page.locator('#P101_USERNAME').count();
    const errorText = await page
      .locator('.apex-page-error, #APEX_ERROR_MESSAGE')
      .first()
      .innerText()
      .catch(() => '');
    if (stillOnLoginForm > 0 && errorText.trim()) {
      console.error(`Login failed: ${errorText.trim()}`);
      process.exit(2);
      return;
    }
    if (stillOnLoginForm > 0) {
      console.error('Login failed: still on the login form after submit (form may have changed shape).');
      process.exit(2);
      return;
    }

    console.log(`Login succeeded. Landed on: ${page.url()}`);
    const instanceMatch = INSTANCE_RE.exec(page.url());
    const instanceId = instanceMatch ? instanceMatch[1] : null;

    let fetched = null;
    if (args.thenUrl) {
      let targetUrl = args.thenUrl;
      if (targetUrl.includes('SESSION')) {
        if (!instanceId) {
          console.error('error: could not extract a post-login instance ID from the landing URL to substitute for SESSION.');
          process.exit(1);
          return;
        }
        targetUrl = targetUrl.replace('SESSION', instanceId);
      }
      console.log(`Navigating to ${targetUrl} in the authenticated session...`);
      const resp = await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: args.timeout * 1000 }).catch(() => null);
      const body = await page.content();
      fetched = { url: targetUrl, finalUrl: page.url(), status: resp ? resp.status() : null, body };
    }

    const allCookies = await context.cookies('https://sonlite.dnr.state.la.us');
    const cookieMap = {};
    for (const c of allCookies) cookieMap[c.name] = c.value;

    fs.mkdirSync(path.dirname(AUTH_PROFILE_FILE), { recursive: true });
    fs.writeFileSync(
      AUTH_PROFILE_FILE,
      JSON.stringify(
        {
          capturedAt: new Date().toISOString(),
          username: args.username,
          cookies: cookieMap,
          landedUrl: page.url(),
        },
        null,
        2
      )
    );
    console.log(`Saved authenticated session -> ${AUTH_PROFILE_FILE}`);

    if (fetched) {
      console.log(JSON.stringify(fetched));
    }
  } finally {
    await stealth.closeContext(context);
  }
}

main().catch((e) => {
  console.error(`\nerror: ${e.message}`);
  process.exit(1);
});
