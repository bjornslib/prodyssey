#!/usr/bin/env node
// Render-proof for the CSP/webview refactor of viewer/index.html.
//
// What this does:
//   1. Serves spike/webview/bundle/ over plain HTTP, rooted so that viewer/ is a sibling
//      of data/ and assets/ — exactly like the real generated bundle layout — with ONE
//      transform applied on the fly, in memory, only to viewer/index.html: the
//      __ODYSSEY_CSP__ and __ODYSSEY_NONCE__ placeholders are substituted with a real
//      strict CSP and a real nonce. The on-disk deliverable file is never modified —
//      this script only rewrites the bytes it serves over the wire.
//   2. Drives that page with Playwright + the pre-installed Chromium (no browser
//      download), instrumenting console/pageerror/requestfailed/CSP-violation events and
//      every outgoing request URL.
//   3. Exercises the viewer: waits for window.STORY, walks levels 1-4, opens an ADR sheet
//      if one is reachable, screenshots each state.
//   4. Prints a PASS/FAIL summary and exits non-zero on failure.
//
// Usage: node render-test.mjs

import http from 'node:http';
import fs from 'node:fs';
import fs_promises from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE_DIR = path.join(__dirname, 'bundle');
const VIEWER_INDEX_REL = path.join('viewer', 'index.html');
const CHROMIUM_PATH = '/opt/pw-browsers/chromium'; // symlink -> chromium-1194/chrome-linux/chrome

const REAL_NONCE = 'ODYSSEYNONCE';
const REAL_CSP =
  "default-src 'none'; img-src 'self' data:; media-src 'self'; font-src 'self'; " +
  "style-src 'self' 'unsafe-inline'; script-src 'nonce-ODYSSEYNONCE'; connect-src 'self';";

const PORT = 8934;
const HOST = '127.0.0.1';
const ORIGIN = `http://${HOST}:${PORT}`;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.wav': 'audio/wav',
  '.woff2': 'font/woff2',
  '.json': 'application/json; charset=utf-8',
  '.yaml': 'text/yaml; charset=utf-8',
  '.ico': 'image/x-icon',
};

function contentTypeFor(filePath) {
  return MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
}

// ---------------------------------------------------------------------------
// Static server. Only viewer/index.html gets its placeholders substituted;
// everything else (data/*.js, assets/*.png, audio/*.wav, vendor/*) is served
// byte-for-byte from disk.
// ---------------------------------------------------------------------------
function startServer() {
  const server = http.createServer(async (req, res) => {
    try {
      const urlPath = decodeURIComponent(new URL(req.url, ORIGIN).pathname);
      let relPath = urlPath.replace(/^\/+/, '');
      if (relPath === '' || relPath.endsWith('/')) relPath += 'index.html';

      const resolved = path.normalize(path.join(BUNDLE_DIR, relPath));
      if (!resolved.startsWith(BUNDLE_DIR)) {
        res.writeHead(403);
        res.end('forbidden');
        return;
      }

      if (relPath === VIEWER_INDEX_REL || relPath === path.join('viewer', '')) {
        const raw = await fs_promises.readFile(path.join(BUNDLE_DIR, VIEWER_INDEX_REL), 'utf8');
        const rendered = raw
          .split('__ODYSSEY_CSP__').join(REAL_CSP)
          .split('__ODYSSEY_NONCE__').join(REAL_NONCE);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(rendered);
        return;
      }

      const stat = await fs_promises.stat(resolved).catch(() => null);
      if (!stat || !stat.isFile()) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': contentTypeFor(resolved) });
      fs.createReadStream(resolved).pipe(res);
    } catch (err) {
      res.writeHead(500);
      res.end('server error: ' + (err && err.message));
    }
  });
  return new Promise((resolve) => {
    server.listen(PORT, HOST, () => resolve(server));
  });
}

// ---------------------------------------------------------------------------
// Test run
// ---------------------------------------------------------------------------
async function main() {
  const screenshotDir = __dirname;
  const server = await startServer();
  console.log(`[server] serving ${BUNDLE_DIR} at ${ORIGIN}`);

  const consoleMessages = [];
  const pageErrors = [];
  const requestFailures = [];
  const cspViolations = [];
  const allRequests = [];
  const externalRequests = [];

  let browser;
  const failures = [];

  try {
    browser = await chromium.launch({
      executablePath: CHROMIUM_PATH,
      headless: true,
      args: ['--no-sandbox'], // container environment; not a CSP-relevant flag
    });

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    page.on('console', (msg) => {
      consoleMessages.push({ type: msg.type(), text: msg.text() });
    });
    page.on('pageerror', (err) => {
      pageErrors.push(String(err && err.stack ? err.stack : err));
    });
    page.on('requestfailed', (req) => {
      requestFailures.push({ url: req.url(), failure: req.failure() && req.failure().errorText });
    });
    page.on('request', (req) => {
      const url = req.url();
      allRequests.push(url);
      try {
        const u = new URL(url);
        const isLocal = u.hostname === HOST || u.hostname === 'localhost' || u.protocol === 'data:';
        if (!isLocal) externalRequests.push(url);
      } catch {
        // ignore malformed URLs (shouldn't happen)
      }
    });

    // Expose a hook the page calls from a securitypolicyviolation listener we inject
    // via addInitScript (runs before any page script, so it catches violations fired
    // during the very first script's execution too).
    await page.exposeFunction('__reportCspViolation__', (detail) => {
      cspViolations.push(detail);
    });
    await page.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', (e) => {
        window.__reportCspViolation__({
          blockedURI: e.blockedURI,
          violatedDirective: e.violatedDirective,
          effectiveDirective: e.effectiveDirective,
          originalPolicy: e.originalPolicy,
          sourceFile: e.sourceFile,
          lineNumber: e.lineNumber,
        });
      });
    });

    console.log('[nav] loading viewer/index.html ...');
    await page.goto(`${ORIGIN}/viewer/index.html`, { waitUntil: 'load', timeout: 30000 });

    // --- window.STORY truthy -------------------------------------------------
    const storyOk = await page.waitForFunction(() => !!window.STORY, null, { timeout: 10000 })
      .then(() => true).catch(() => false);
    if (!storyOk) failures.push('window.STORY did not become truthy within timeout');
    else console.log('[check] window.STORY is truthy: PASS');

    // --- diffs-ready contract actually resolved -------------------------------
    const diffsOk = await page.evaluate(async () => {
      if (!window.__ODYSSEY_DIFFS_READY__) return { ok: false, reason: 'no __ODYSSEY_DIFFS_READY__ promise' };
      await window.__ODYSSEY_DIFFS_READY__;
      return { ok: true, hasDiffs: !!(window.DIFFS_BY_PR && Object.keys(window.DIFFS_BY_PR).length) };
    });
    if (!diffsOk.ok) failures.push('diffs-ready contract failed: ' + diffsOk.reason);
    else console.log(`[check] diff loader resolved, window.DIFFS_BY_PR populated: ${diffsOk.hasDiffs} (PASS)`);

    // --- level 1 renders visible text from the story -------------------------
    await page.waitForSelector('#rail-items .rail-item', { timeout: 10000 });
    const prLabel = await page.locator('#tb-pr-label').innerText();
    const level1Text = await page.locator('#main-content').innerText();
    console.log(`[check] topbar PR label: "${prLabel.trim()}"`);
    if (!prLabel.trim()) failures.push('topbar PR label is empty on level 1');
    if (!level1Text.trim()) failures.push('level 1 main-content has no visible text');
    else console.log('[check] level 1 renders visible text: PASS');
    await page.screenshot({ path: path.join(screenshotDir, 'render-level1.png'), fullPage: true });
    console.log('[screenshot] render-level1.png');

    // --- navigate levels 2, 3, 4 via the rail ---------------------------------
    for (const level of [2, 3, 4]) {
      const railItem = page.locator(`.rail-item[data-level="${level}"]`);
      await railItem.click();
      await page.waitForFunction(
        (lvl) => document.querySelector(`.rail-item[data-level="${lvl}"]`)?.classList.contains('active'),
        level,
        { timeout: 5000 }
      );
      // let the content-transition animation (or its safety-timer fallback) settle
      await page.waitForTimeout(500);
      const text = await page.locator('#main-content').innerText();
      if (!text.trim()) failures.push(`level ${level} main-content has no visible text`);
      else console.log(`[check] level ${level} renders visible text: PASS`);

      // Level 4 exercises the CSP-safe diff loader end to end: click "view diff" on the
      // first file row that has one and confirm real diff text (not the "not captured"
      // fallback) renders — proves window.DIFFS_BY_PR was truly populated in time, not
      // just non-empty as an object.
      if (level === 4) {
        const diffBtn = page.locator('.fr-diffbtn').first();
        const diffBtnCount = await diffBtn.count();
        if (diffBtnCount > 0) {
          await diffBtn.click();
          await page.waitForTimeout(150);
          const diffBody = await page.locator('.fr-diffbody:not([hidden])').first().innerText().catch(() => '');
          if (!diffBody.trim()) failures.push('clicking "view diff" on level 4 did not reveal diff content');
          else console.log('[check] level 4 diff expansion shows real diff content: PASS');
        } else {
          console.log('[check] no "view diff" buttons on level 4 for this PR — skipping diff-expansion check');
        }
      }

      await page.screenshot({ path: path.join(screenshotDir, `render-level${level}.png`), fullPage: true });
      console.log(`[screenshot] render-level${level}.png`);
    }

    // --- ADR badge on level 3, if reachable -----------------------------------
    await page.locator('.rail-item[data-level="3"]').click();
    await page.waitForFunction(
      () => document.querySelector('.rail-item[data-level="3"]')?.classList.contains('active'),
      null, { timeout: 5000 }
    );
    await page.waitForTimeout(500);
    const adrBadge = page.locator('.adr-badge').first();
    const adrCount = await adrBadge.count();
    if (adrCount > 0) {
      await adrBadge.click();
      await page.waitForSelector('#adr-sheet.open', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(350); // sheet slide-in transition
      const sheetOpen = await page.locator('#adr-sheet.open').count();
      if (!sheetOpen) failures.push('ADR badge click did not open #adr-sheet');
      else console.log('[check] ADR sheet opened: PASS');
      const adrTitle = await page.locator('#adr-sheet-title').innerText().catch(() => '');
      console.log(`[check] ADR sheet title: "${adrTitle.trim()}"`);
      await page.screenshot({ path: path.join(screenshotDir, 'render-adr.png'), fullPage: true });
      console.log('[screenshot] render-adr.png');
    } else {
      console.log('[check] no ADR badge reachable on level 3 for this PR — skipping ADR screenshot');
    }

    await context.close();
  } catch (err) {
    failures.push('unhandled exception during run: ' + (err && err.stack ? err.stack : err));
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }

  // --- external-request audit -------------------------------------------------
  if (externalRequests.length) {
    failures.push(`${externalRequests.length} request(s) hit a non-local host: ${JSON.stringify(externalRequests)}`);
  }

  // --- console error/warning audit ---------------------------------------------
  const consoleErrors = consoleMessages.filter((m) => m.type === 'error');
  const consoleWarnings = consoleMessages.filter((m) => m.type === 'warning');
  if (consoleErrors.length) {
    failures.push(`${consoleErrors.length} console error(s): ${JSON.stringify(consoleErrors)}`);
  }

  if (pageErrors.length) {
    failures.push(`${pageErrors.length} uncaught page error(s): ${JSON.stringify(pageErrors)}`);
  }
  if (requestFailures.length) {
    failures.push(`${requestFailures.length} failed request(s): ${JSON.stringify(requestFailures)}`);
  }
  if (cspViolations.length) {
    failures.push(`${cspViolations.length} CSP violation(s): ${JSON.stringify(cspViolations)}`);
  }

  // --- summary -------------------------------------------------------------
  console.log('\n========================= SUMMARY =========================');
  console.log('CSP used:', REAL_CSP);
  console.log('Total requests observed:', allRequests.length);
  for (const u of allRequests) console.log('  req:', u);
  console.log('External (non-local) requests:', externalRequests.length);
  if (externalRequests.length) console.log('  ->', externalRequests);
  console.log('Console messages:', consoleMessages.length, `(errors: ${consoleErrors.length}, warnings: ${consoleWarnings.length})`);
  if (consoleMessages.length) {
    for (const m of consoleMessages) console.log(`  [console:${m.type}] ${m.text}`);
  }
  console.log('Page errors:', pageErrors.length);
  if (pageErrors.length) for (const e of pageErrors) console.log('  ->', e);
  console.log('Failed requests:', requestFailures.length);
  if (requestFailures.length) for (const r of requestFailures) console.log('  ->', r);
  console.log('CSP violations:', cspViolations.length);
  if (cspViolations.length) for (const v of cspViolations) console.log('  ->', JSON.stringify(v));
  console.log('=============================================================\n');

  if (failures.length) {
    console.log(`FAIL (${failures.length} issue(s)):`);
    for (const f of failures) console.log(' -', f);
    process.exitCode = 1;
  } else {
    console.log('PASS: viewer rendered all four levels under a strict nonce-based CSP with zero external requests, zero console errors, zero CSP violations.');
    process.exitCode = 0;
  }
}

main();
