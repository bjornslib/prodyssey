# Findings — CSP/webview spike for the Prodyssey viewer

**Verdict: PASS.** The refactored viewer boots and renders all four levels (plus the ADR
sheet and an expanded inline diff) under a strict nonce-based CSP with **zero** external
network requests, **zero** console errors, **zero** page errors, **zero** failed requests,
and **zero** `securitypolicyviolation` events, proven by a headless-Chromium Playwright run
(`render-test.mjs`) against the real `digital-curator-80f83abb` bundle. Screenshots for
every state are in this directory.

Everything below lives under `spike/webview/`. Nothing outside `spike/` and nothing at
`viewer/index.html` was touched.

## Scope of the diff

The refactor is a copy of `viewer/index.html` (confirmed byte-identical to the fixture's
own `viewer/index.html` before editing) with **only** these changes: a CSP `<meta>` tag,
`nonce` attributes on the six `<script>` tags, two CDN links replaced with local vendor
files, and the `document.write` diff-loader replaced with an equivalent dynamic-injection
loader. No CSS rule, no DOM structure, no application/render logic, no `localStorage` key,
and no user-facing copy was changed. The line numbers below refer to
`spike/webview/bundle/viewer/index.html` (2078 lines vs. the original 1990 — growth is
entirely the inlined `@font-face` block and the loader's explanatory comments).

### 1a — CSP meta tag (line 5)

```html
<meta http-equiv="Content-Security-Policy" content="__ODYSSEY_CSP__">
```

Inserted as the first element in `<head>`, immediately after the `<meta charset>` and
before `<meta name="viewport">` (the task said "after the charset meta"; viewport is
functionally interchangeable with CSP ordering, this just keeps charset unambiguously
first as required by the HTML spec). Left as the literal placeholder on disk — the render
test substitutes a real value at serve time (see "CSP used in the test" below). A real VS
Code extension host would substitute its own per-load nonce/CSP the same way (typically via
`webview.cspSource` and a freshly generated nonce per `resolveWebviewView` call).

### 1b — `nonce="__ODYSSEY_NONCE__"` on every `<script>` tag

All six `<script>` tags now carry the placeholder nonce attribute:

| Line | Tag |
|---|---|
| 9 | `vendor/motion.min.js` |
| 644 | `../data/story.js` |
| 645 | `../data/manifest.js` |
| 646 | inline diff-loader script |
| 678 | `../data/adrs.js` |
| 679 | inline application script |

Verified with `grep -c` that the placeholder appears exactly 7 times on disk (1x in the
CSP meta content, 6x as `nonce="..."` on the script tags) and that none were missed.

### 1c — Localized CDN dependencies

**Motion** (`spike/webview/bundle/viewer/vendor/motion.min.js`, 139,680 bytes): downloaded
verbatim from `https://cdn.jsdelivr.net/npm/motion@12/dist/motion.min.js` via `curl`
through the environment's HTTPS proxy, byte count matches the CDN's `Content-Length`
exactly. Referenced locally as `<script src="vendor/motion.min.js" nonce="__ODYSSEY_NONCE__">`
(line 9). `window.Motion.animate` usage in the app script is completely unchanged — the
existing `anim()` helper already no-ops gracefully if `window.Motion` is absent, so this
swap is transparent either way.

**JetBrains Mono** (`spike/webview/bundle/viewer/vendor/fonts/`): fetched the real Google
Fonts CSS (`css2?family=JetBrains+Mono:wght@400;600;700&display=swap`) with a
Chrome-flavored `User-Agent` to get woff2 URLs (Google varies the response format by
`Accept`/`UA`), then downloaded all 6 referenced `.woff2` files (66 KB total — one per
Unicode subset: latin, latin-ext, cyrillic, cyrillic-ext, greek, vietnamese). Each file
turned out to be a single variable-weight instrument that Google's own CSS reuses across
the 400/600/700 declarations (identical URL for a given subset regardless of weight) — so
the self-hosted version mirrors that with 6 `@font-face` rules total (one per subset) using
a `font-weight: 400 700` range each, rather than 18 near-duplicate rules. Inlined directly
into the existing `<style>` block (lines 19-65) rather than a linked stylesheet — a literal
reading of the task's "adding a local `@font-face` in a `<style>` block," and it keeps
`font-src` scoped to `'self'` with the CSS itself costing zero extra requests. (A copy of
the rules also exists as `vendor/fonts/jetbrains-mono.css` for reference/provenance; it is
not linked from the HTML.) The `<link rel="preconnect" href="https://fonts.googleapis.com">`
and the Google Fonts `<link rel="stylesheet">` were both deleted outright (no replacement
needed once the fonts are local).

Font self-hosting was **not** a fallback — it worked cleanly on the first attempt, so
`font-src 'self'` holds with the real JetBrains Mono, not a `monospace` stand-in. The
render-test's request log shows only `jetbrains-mono-latin.woff2` was actually fetched at
runtime (browsers only pull the Unicode-range subset(s) that match characters present on
the page; this bundle's story text is all-ASCII, so only the `latin` subset loads).

### 1d — `document.write` diff loader replaced (lines 646-677, 679-689)

The original (line ~592 in `viewer/index.html`):

```js
((window.ODYSSEY && window.ODYSSEY.diff_prs) || []).forEach(function(n){
  document.write('<script src="../data/diffs-pr' + n + '.js"><\/script>');
});
```

relies on `document.write`'s synchronous, parser-blocking script injection to guarantee
`window.DIFFS_BY_PR` is fully populated before the very next `<script>` tag (`adrs.js`,
then the app IIFE) begins executing. Under a strict CSP, `document.write` of a `<script>`
is either blocked outright or simply produces a script tag with no `nonce`, which the CSP
then drops — either way it's not usable.

Replacement, at line 646:

```js
window.__ODYSSEY_DIFFS_READY__ = (function(){
  const prs = (window.ODYSSEY && window.ODYSSEY.diff_prs) || [];
  const nonce = document.currentScript && (document.currentScript.nonce || document.currentScript.getAttribute('nonce'));
  return Promise.all(prs.map(function(n){
    return new Promise(function(resolve){
      const s = document.createElement('script');
      s.src = '../data/diffs-pr' + n + '.js';
      if (nonce) s.nonce = nonce;
      s.addEventListener('load', function(){ resolve(); });
      s.addEventListener('error', function(err){
        console.error('[odyssey] failed to load diff bundle for PR #' + n, err);
        resolve(); // never let a missing/broken diff bundle wedge app boot
      });
      document.head.appendChild(s);
    });
  }));
})();
```

Each diff script is built as a real DOM `<script>` element and given the **same** nonce the
loader script itself was executed with. That nonce is read off `document.currentScript`
using the `.nonce` **property**, not `getAttribute('nonce')` — browsers scrub the reflected
`nonce` attribute from the DOM immediately after a nonce'd script is allowed to run
(specifically so a later injection/XSS can't just read a valid nonce off an existing tag),
so `getAttribute` alone would silently come back empty in some browsers/versions. The
`.nonce` IDL property survives that scrub for the tag's own script to read.

To preserve the original "diffs are ready before the app runs" contract without touching
the app's internal render logic, the app's top-level IIFE (line 682) was changed from
`(function(){` to `(async function(){`, with one line added right after `'use strict';`
(line 689):

```js
await (window.__ODYSSEY_DIFFS_READY__ || Promise.resolve());
```

This was the trickiest part of the refactor to get right — not the mechanics of building
`<script>` elements dynamically (straightforward), but deciding *where* to re-establish the
ordering guarantee that `document.write` used to give for free. The chosen approach — await
a single readiness promise as the very first statement of the app IIFE — is a two-line
change that preserves the full contract exactly (nothing in the app runs until every diff
bundle has loaded or failed), is trivially auditable, and doesn't require threading a
"diffs ready" callback through `renderMainContent`/`toggleDiff`/etc. A failed diff-script
load resolves (not rejects) so one broken PR's diff bundle can never wedge the entire app
boot — it just leaves that PR's diffs showing "diff not captured in prototype", the same
graceful-degradation behavior the app already has for PRs with no captured diffs at all.

Proven end-to-end by the render test, not just inferred: it awaits
`window.__ODYSSEY_DIFFS_READY__` directly from the page, confirms `window.DIFFS_BY_PR` is
populated, then **clicks "view diff" on level 4 and asserts real diff text appears** (not
the "not captured" fallback) — see `render-level4.png`, which shows an expanded diff with
correctly color-coded added/removed lines for `desktop/src/main/clipboard-monitor.ts`.

## CSP used in the test

Exactly as specified in the task, substituted at serve time (not on disk):

```
default-src 'none'; img-src 'self' data:; media-src 'self'; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'nonce-ODYSSEYNONCE'; connect-src 'self';
```

`render-test.mjs` runs a plain Node `http` server rooted at `spike/webview/bundle/` (so
`viewer/`, `data/`, and `assets/` are siblings, matching the real bundle layout and the
`../data/...` / `../assets/...` relative paths the app already uses). It serves every file
byte-for-byte from disk **except** `viewer/index.html`, which is read into memory and has
`__ODYSSEY_CSP__` -> the CSP above and `__ODYSSEY_NONCE__` -> `ODYSSEYNONCE` substituted
before being sent — the on-disk deliverable keeps the literal placeholders untouched, as
required.

## Console / pageerror / CSP-violation results

All three are empty across every run:

```
Console messages: 0 (errors: 0, warnings: 0)
Page errors: 0
Failed requests: 0
CSP violations: 0
```

CSP-violation detection is not just "absence of console noise" — the page has a
`securitypolicyviolation` listener installed via `page.addInitScript` (so it's live before
any page script executes, catching violations even from the very first `<script>` tag),
wired through `page.exposeFunction` back into the Node test process. Zero violation events
were ever recorded.

## External-request audit

**Zero** external requests. Every one of the 10 requests the page made resolved to
`127.0.0.1:8934` (the test's own local server):

```
http://127.0.0.1:8934/viewer/index.html
http://127.0.0.1:8934/viewer/vendor/motion.min.js
http://127.0.0.1:8934/data/story.js
http://127.0.0.1:8934/viewer/vendor/fonts/jetbrains-mono-latin.woff2
http://127.0.0.1:8934/data/manifest.js
http://127.0.0.1:8934/data/diffs-pr1.js
http://127.0.0.1:8934/data/adrs.js
http://127.0.0.1:8934/assets/pr-1/level-1.png
http://127.0.0.1:8934/assets/pr-1/level-2.png
http://127.0.0.1:8934/assets/pr-1/level-3.png
```

No `cdn.jsdelivr.net`, no `fonts.googleapis.com`/`fonts.gstatic.com`, no other non-local
host appears anywhere in the request log. (Audio `.wav` files were never requested because
`narrationAudio.preload = 'none'` and playback is manual/click-triggered — the test doesn't
click the audio button, see "Residual concerns" below.)

## Render proof

`node render-test.mjs` (also `npm test` from `spike/webview/`) — full run:

```
[server] serving .../spike/webview/bundle at http://127.0.0.1:8934
[nav] loading viewer/index.html ...
[check] window.STORY is truthy: PASS
[check] diff loader resolved, window.DIFFS_BY_PR populated: true (PASS)
[check] topbar PR label: "PR #1 . Extension Ux Electron Port Xaywq7"
[check] level 1 renders visible text: PASS
[screenshot] render-level1.png
[check] level 2 renders visible text: PASS
[screenshot] render-level2.png
[check] level 3 renders visible text: PASS
[screenshot] render-level3.png
[check] level 4 renders visible text: PASS
[check] level 4 diff expansion shows real diff content: PASS
[screenshot] render-level4.png
[check] ADR sheet opened: PASS
[check] ADR sheet title: "Run on-device inference in a hidden BrowserWindow, not onnxruntime-node"
[screenshot] render-adr.png

PASS: viewer rendered all four levels under a strict nonce-based CSP with zero external
requests, zero console errors, zero CSP violations.
```

Exit code `0`. Screenshots (this directory):

- `render-level1.png` — Overview: hero art (scene render), district-touch boxes,
  legend, topbar/rail/dock all visible, JetBrains Mono rendering correctly in labels.
- `render-level2.png` — Problem & Solution: hero art, background/intuition/problem/solution
  2x2 card grid.
- `render-level3.png` — Architecture: hero art, ADR badges (`ADR-0001`, `ADR-0002`),
  district boxes.
- `render-level4.png` — File Changes: file-group accordion, `view diff` expanded on
  `desktop/src/main/clipboard-monitor.ts` showing real, correctly-colorized diff content.
- `render-adr.png` — ADR detail sheet open over level 3, showing problem/decision/rejected
  alternatives/forces for ADR-0001, including the markdown renderer's output.

## Verdict: renders equivalently to the original

Yes, with direct visual evidence, not just code-diff reasoning. As an extra check (not part
of the required deliverable, done to substantiate this section) the unmodified fixture's
`viewer/index.html` — live CDN deps, no CSP, no nonces — was run through the same
Playwright/Chromium harness pointed at a second local server. Level 1 renders visually
equivalent to `render-level1.png`: same layout, same hero art, same JetBrains Mono
rendering in the topbar/rail/labels, same colors. Interestingly, that unmodified run logged
two `net::ERR_CONNECTION_RESET` console errors from the CDN requests (this sandbox's
outbound network to `fonts.googleapis.com`/`cdn.jsdelivr.net` is not perfectly reliable) —
concrete evidence, beyond the abstract webview argument, for why removing the CDN
dependency is worth doing even outside the CSP requirement.

Since the refactor changes zero CSS, zero DOM structure, and zero render/state logic — only
adding a CSP meta tag, nonce attributes (inert unless a CSP with `script-src 'nonce-...'` is
actually present), swapping two CDN URLs for byte-identical/functionally-identical local
files, and replacing one loader's mechanism while preserving its ordering contract — visual
and behavioral equivalence was expected, and the screenshots confirm it holds.

## Residual concerns for the real webview integration

- **Audio autoplay / `Audio()` element.** The render test never clicks the narration-audio
  button (audio playback wasn't in the required assertion list), so this refactor has not
  exercised `new Audio()` + `.play()` under a real VS Code webview's autoplay policy. VS
  Code webviews are Electron/Chromium-based and generally allow user-gesture-triggered
  `<audio>`/`Audio()` playback (this app's audio is manual click/keypress-triggered, never
  autoplaying), so it should be fine, but it wasn't proven here and should be smoke-tested
  in the real extension host. `media-src 'self'` in the test CSP is already correct for
  this — the `.wav` files are same-origin under `asWebviewUri`.
- **`asWebviewUri` path rewriting.** This spike serves the bundle over plain
  `http://127.0.0.1`, where relative paths (`../data/story.js`, `vendor/motion.min.js`,
  `../assets/pr-1/level-1.png`) resolve exactly as authored. A real VS Code webview instead
  serves content through `vscode-webview://` URIs and requires every local resource
  reference to be rewritten via `webview.asWebviewUri(...)` — relative `src`/`href`
  attributes in static HTML are **not** automatically rewritten by the webview host. This
  viewer's relative-path assumption (`../data/...`, `vendor/...`, `../assets/...`) is
  webview-compatible only if the extension either (a) constructs the full HTML at runtime
  and substitutes `asWebviewUri`-resolved URIs in place of these relative paths, or (b) the
  webview's `localResourceRoots` is set broadly enough and VS Code's relative-URI resolution
  inside a webview document root happens to line up — this needs verification against the
  actual extension host, not assumed from this static-HTTP spike.
- **`data:` favicon.** `<link rel="icon" href="data:,">` was left as-is; it's an empty
  `data:` URI (effectively "no icon") and never triggers a request, so it's inert under any
  CSP tested here — but note it relies on `img-src` implicitly allowing `data:` (which the
  test CSP does grant, via `img-src 'self' data:`) or on `default-src` covering favicons
  loosely in practice. Not a real risk, just noting it's the one non-`'self'`-only resource
  reference left in the file.
- **`document.currentScript` inside a dynamically-injected script.** The diff-loader reads
  `document.currentScript.nonce` at the time the *loader* script (a static `<script
  nonce="...">` tag) runs — this is well-defined and reliable. It does **not** rely on
  `document.currentScript` inside any dynamically-created `<script>` element (those get
  their nonce set directly as a property before being appended), which is good, since
  `document.currentScript` semantics for programmatically-inserted scripts are inconsistent
  across engines.
- **Diff-loader failure mode.** A missing/renamed `diffs-pr<N>.js` now resolves gracefully
  (logs a console error, doesn't reject) rather than the old behavior where a 404'd
  `document.write`d script would have also just been a no-op *and* not delayed anything
  (since document.write injection was synchronous but a 404 doesn't throw either) — net
  effect is the same graceful degradation, now just explicit instead of accidental.
- **CSP is applied via `<meta http-equiv>`, not an HTTP response header.** This matches how
  VS Code webviews actually set CSP (there's no HTTP layer to attach a header to — content
  is injected as an HTML string via `webview.html = ...`), so this is the *correct* delivery
  mechanism for the target environment, not a shortcut. It's called out here only because a
  meta-tag CSP behaves slightly differently from a header CSP in one respect not relevant to
  this app: it cannot set `frame-ancestors` or `report-uri`/`report-to` (both silently
  ignored in a meta tag per spec) — neither directive was needed here.

## Files

- `spike/webview/bundle/viewer/index.html` — refactored viewer, `__ODYSSEY_CSP__` /
  `__ODYSSEY_NONCE__` placeholders intact on disk.
- `spike/webview/bundle/viewer/vendor/motion.min.js` — self-hosted Motion UMD build.
- `spike/webview/bundle/viewer/vendor/fonts/*.woff2` (6 files) + `jetbrains-mono.css`
  (reference copy, not linked from HTML) — self-hosted JetBrains Mono.
- `spike/webview/bundle/data/`, `spike/webview/bundle/assets/`,
  `spike/webview/bundle/inventory.yaml` — copied unmodified from
  `.prodyssey/digital-curator-80f83abb/` (the `.json` duplicates of `story`/`adrs`/`prompts`
  were dropped since the viewer only ever loads the `.js` globals-assignment versions).
- `spike/webview/render-test.mjs` — Playwright render proof (`npm test` or
  `node render-test.mjs`).
- `spike/webview/render-level1.png` ... `render-level4.png`, `render-adr.png` — screenshots.
