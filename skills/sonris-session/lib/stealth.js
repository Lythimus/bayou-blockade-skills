/**
 * lib/stealth.js — Playwright launch hardening shared by the headful solve
 * (sonris_session.js) and the browser transport (lib/transports.js).
 *
 * Goal is coherence, not novelty: everything here makes the automated
 * browser look like the same macOS Chrome/Brave install a human already
 * has, rather than Playwright's bundled Chromium driven with default
 * automation flags. No behavioral simulation (mouse curves, typing
 * cadence) — that crosses from "look like the browser I actually am" into
 * active evasion, which is out of scope here.
 */

const fs = require('fs');
const path = require('path');

const CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
];
const BRAVE_PATHS = [
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
];

function firstExisting(paths) {
  for (const p of paths) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (e) {
      // ignore
    }
  }
  return null;
}

function findChromeExecutable() {
  return firstExisting(CHROME_PATHS);
}

function findBraveExecutable() {
  return firstExisting(BRAVE_PATHS);
}

function hasBundledChromium() {
  try {
    // playwright ships its own download manifest lookup; cheapest check
    // that doesn't require launching a browser is just resolving the
    // package itself — chromium.launchPersistentContext will fail loudly
    // and specifically if no browser is actually installed.
    require.resolve('playwright');
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Returns { executablePath } for the real installed Chrome/Brave binary,
 * or {} to fall back to Playwright's bundled Chromium.
 */
function pickExecutable() {
  const chrome = findChromeExecutable();
  if (chrome) return { executablePath: chrome };
  const brave = findBraveExecutable();
  if (brave) return { executablePath: brave };
  return {};
}

// Deleting navigator.webdriver and patching the handful of properties a
// stock Playwright/Chromium session leaves inconsistent. Function.prototype
// .toString is wrapped last so the patches made above also report as
// native code, not as this script's own source.
const STEALTH_INIT_SCRIPT = `
(() => {
  const nativeToString = Function.prototype.toString;
  const patchedFns = new Set();

  function markNative(fn) {
    patchedFns.add(fn);
    return fn;
  }

  Object.defineProperty(Function.prototype, 'toString', {
    value: markNative(function toString() {
      if (patchedFns.has(this) && this !== toString) return 'function () { [native code] }';
      return nativeToString.call(this);
    }),
    writable: true,
    configurable: true,
  });

  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: markNative(() => undefined),
      configurable: true,
    });
  } catch (e) {}

  try {
    Object.defineProperty(Navigator.prototype, 'languages', {
      get: markNative(() => ['en-US', 'en']),
      configurable: true,
    });
  } catch (e) {}

  try {
    const pdfPlugin = {
      name: 'Chrome PDF Plugin',
      filename: 'internal-pdf-viewer',
      description: 'Portable Document Format',
    };
    const pdfViewerPlugin = {
      name: 'Chrome PDF Viewer',
      filename: 'internal-pdf-viewer',
      description: '',
    };
    const nacl = {
      name: 'Native Client',
      filename: 'internal-nacl-plugin',
      description: '',
    };
    const fakePlugins = [pdfPlugin, pdfViewerPlugin, nacl];
    fakePlugins.item = (i) => fakePlugins[i];
    fakePlugins.namedItem = (name) => fakePlugins.find((p) => p.name === name);
    Object.defineProperty(Navigator.prototype, 'plugins', {
      get: markNative(() => fakePlugins),
      configurable: true,
    });
    Object.defineProperty(Navigator.prototype, 'mimeTypes', {
      get: markNative(() => {
        const types = [
          { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: pdfPlugin },
          { type: 'text/pdf', suffixes: 'pdf', description: '', enabledPlugin: pdfPlugin },
        ];
        types.item = (i) => types[i];
        types.namedItem = (name) => types.find((t) => t.type === name);
        return types;
      }),
      configurable: true,
    });
  } catch (e) {}

  try {
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};
  } catch (e) {}

  try {
    const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (originalQuery) {
      window.navigator.permissions.query = markNative((params) =>
        params && params.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : originalQuery(params)
      );
    }
  } catch (e) {}

  try {
    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = markNative(function getParameter(parameter) {
      // UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL
      if (parameter === 37445) return 'Apple Inc.';
      if (parameter === 37446) return 'Apple GPU';
      return getParameterProto.call(this, parameter);
    });
  } catch (e) {}
})();
`;

function launchOptions(profileDir, opts = {}) {
  return {
    headless: opts.headless || false,
    viewport: { width: 1512, height: 945 },
    deviceScaleFactor: 2,
    hasTouch: false,
    locale: 'en-US',
    timezoneId: 'America/Chicago',
    ignoreDefaultArgs: ['--enable-automation', '--disable-extensions'],
    args: ['--disable-blink-features=AutomationControlled'],
    ...pickExecutable(),
    ...opts.overrides,
  };
}

// Documents are fetched from inside the page (lib/transports.js), never
// navigated to, so Chrome's PDF handling is not on the request path. The
// pref is set explicitly *off* because an existing profile may carry `true`:
// with it on, a PDF navigation becomes a download, and Playwright-managed
// downloads crash installed Chrome 154 on macOS (EXC_BAD_ACCESS ~3 s after
// launch) — a "Google Chrome quit unexpectedly" dialog for the user each time.
// Must only run before launch; Chrome rewrites Preferences while running.
function ensurePdfDownloadPref(profileDir) {
  const defaultDir = path.join(profileDir, 'Default');
  fs.mkdirSync(defaultDir, { recursive: true });
  const prefsPath = path.join(defaultDir, 'Preferences');
  let prefs = {};
  try {
    prefs = JSON.parse(fs.readFileSync(prefsPath, 'utf8'));
  } catch (e) {
    // no existing prefs file, or unreadable — start fresh
  }
  prefs.plugins = prefs.plugins || {};
  prefs.plugins.always_open_pdf_externally = false;
  fs.writeFileSync(prefsPath, JSON.stringify(prefs));
}

async function launchStealthContext(chromium, profileDir, opts = {}) {
  ensurePdfDownloadPref(profileDir);
  const context = await chromium.launchPersistentContext(profileDir, launchOptions(profileDir, opts));
  await context.addInitScript(STEALTH_INIT_SCRIPT);
  return context;
}

/**
 * Quits the browser the way Cmd-Q would. context.close() on a persistent
 * context with installed Chrome hangs ~30 s before Playwright kills the
 * process, leaving Chrome's "didn't shut down correctly" state in the
 * profile; CDP Browser.close exits cleanly in ~100 ms.
 */
async function closeContext(context) {
  if (!context) return;
  const closed = new Promise((resolve) => context.once('close', resolve));
  try {
    const browser = context.browser();
    if (browser) {
      const cdp = await browser.newBrowserCDPSession();
      await cdp.send('Browser.close').catch(() => {});
      await Promise.race([closed, new Promise((r) => setTimeout(r, 10000))]);
    }
  } catch (e) {
    // fall through to Playwright's own close
  }
  await context.close().catch(() => {});
}

module.exports = {
  findChromeExecutable,
  findBraveExecutable,
  hasBundledChromium,
  pickExecutable,
  launchOptions,
  launchStealthContext,
  closeContext,
  ensurePdfDownloadPref,
  STEALTH_INIT_SCRIPT,
};
