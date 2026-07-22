# Prodyssey VS Code extension spike — local test runbook

This runbook is for the USER, running on their own machine (not the cloud
container this spike was built in). Nothing in `spike/host/` has made a live
Anthropic or Gemini API call yet — this is the first point that will.

## 0. Prerequisites on your machine

- VS Code (desktop, with GUI — this cannot be verified in the cloud spike
  environment).
- Node.js >= 18 (the installed SDK's `engines.node` floor; the repo used
  Node 22 during the spike).
- `uv` on PATH (https://docs.astral.sh/uv/getting-started/installation/) —
  the odyssey skill's scripts are invoked via `uv run`.
- `python3` on PATH.
- An `ANTHROPIC_API_KEY`, OR be logged in via `claude login` (subscription
  OAuth) so `CLAUDE_CODE_OAUTH_TOKEN`/persisted credentials are available —
  see FINDINGS.md section 2c for why either works.
- A `GEMINI_API_KEY` (https://aistudio.google.com/apikey) — required for
  Generate mode's scene art + narration sweep.
- A small git repo to point Prodyssey at (a few merged PRs' worth of
  history is enough for a first smoke test — don't start with something
  huge).

## 1. Get the code onto your machine and open it

```bash
git clone <this repo>
cd prodyssey
code spike/host
```

(Or `File > Open Folder...` on `spike/host/` from inside VS Code.)

## 2. Install and build

From an integrated terminal inside `spike/host/`:

```bash
npm install
npm run copy-plugin   # copies ../../.claude-plugin, skills/, scripts/, viewer/ into ./plugin/
npm run compile       # esbuild: src/extension.ts -> dist/extension.js
```

`npm install` will pull down `@anthropic-ai/claude-agent-sdk` and, as an
optional dependency, the ~260-270 MB native `claude` binary for your
platform (see FINDINGS.md 2a — this is expected and is not a mistake in the
install; the SDK spawns that binary, it does not run in-process). Expect
`node_modules/` to land around 500 MB - 1 GB depending on platform.

Expected output: `dist/extension.js` and `dist/extension.js.map` exist, and
`plugin/` contains `.claude-plugin/`, `skills/odyssey/`, `scripts/*.py`, and
`viewer/index.html`.

## 3. Launch the Extension Development Host

Press **F5** (or Run > Start Debugging) with `spike/host/` as the open
folder. VS Code will open a second "[Extension Development Host]" window
with this spike extension active in it.

If F5 doesn't pick up a launch config automatically, add a minimal
`.vscode/launch.json` in `spike/host/`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "extensionHost",
      "request": "launch",
      "name": "Run Prodyssey (spike)",
      "runtimeExecutable": "${execPath}",
      "args": ["--extensionDevelopmentPath=${workspaceFolder}"],
      "outFiles": ["${workspaceFolder}/dist/**/*.js"],
      "preLaunchTask": "npm: compile"
    }
  ]
}
```

## 4. Open a target repo in the Extension Development Host

In the new "[Extension Development Host]" window, `File > Open Folder...`
and pick the small git repo you want to analyze (this is the `cwd`/target
repo the extension will drive Prodyssey against — it does NOT need to be
this `prodyssey` repo itself).

## 5. Run "Prodyssey: Baseline" first

Open the command palette (Cmd/Ctrl+Shift+P) and run **"Prodyssey:
Baseline"**.

Expected flow:

1. The extension checks `which uv` / `which python3` (or `where` on
   Windows) and errors out with an actionable message if either is
   missing.
2. It resolves the target repo from the open workspace folder.
3. It prompts for `ANTHROPIC_API_KEY` via an input box (password-masked) —
   you can leave this blank if you're relying on `claude login`/subscription
   OAuth. Whatever you enter is stored in VS Code's `SecretStorage` (OS
   keychain-backed), so you won't be asked again on subsequent runs in the
   same installed extension.
4. It prompts for `GEMINI_API_KEY` the same way.
5. It opens the "Prodyssey" output channel and a progress notification, then
   drives the bundled `odyssey` skill's Baseline mode against your target
   repo via the SDK's `query()` — **this is the first live network call**:
   it spawns the native `claude` binary, which talks to the real Anthropic
   API (and, for baseline mode, should NOT need Gemini — see FINDINGS.md
   2a/2c and `skills/odyssey/SKILL.md`'s Step 0 gate for why the Gemini key
   check is Generate-specific).
6. Progress messages should stream into both the notification and the
   output channel (e.g. "starting odyssey session", "inspecting repo
   history", "mapping repo architecture", ...).
7. On success, expect a `.odyssey/` (or `.prodyssey/<slug>/` for a
   centrally-stored bundle — see `SKILL.md`'s Hub resolution section)
   directory to appear in the target repo, containing `data/story.json`,
   `inventory.yaml`, and a copied `viewer/index.html`.

## 6. Run "Prodyssey: Generate"

Run **"Prodyssey: Generate"** from the command palette. You'll additionally
be prompted for a PR selection string (defaults to `--latest`). This drives
the full per-PR sweep: narrative authoring, ADR extraction, scene art
(Gemini), and voice narration (Gemini) — expect this to take noticeably
longer and to actually spend Gemini API credits.

**Known gap to expect here, not a regression to chase:** per FINDINGS.md's
delta notes, this spike's `canUseTool` only auto-approves
`Read`/`Grep`/`Glob`/`Bash` (with Bash further restricted to `uv run`,
`git`, `python3 -m http.server`, `mkdir`, `cp`, `ln` prefixes). The real
`odyssey` skill's narrative-authoring step describes editing `story.json`/
`adrs.json` directly, which needs `Write`/`Edit` tool access this sanctioned
surface does not grant. If Generate mode stalls on a permission
denial for a `Write`/`Edit` call, that is this known, documented gap — not
a surprise. Extending `SANCTIONED_TOOLS`/`buildCanUseTool` in
`src/odysseyHost.ts` to include `Write`/`Edit` under the same
cwd-containment check used for `Read` is the fix, left for the next phase
rather than this spike.

## 7. Run "Prodyssey: View Story"

Run **"Prodyssey: View Story"**. This opens a Webview panel loading the
bundled `plugin/viewer/index.html`.

**Known gap to expect here too:** per FINDINGS.md's "Integration seam"
section, today's `viewer/index.html` doesn't yet contain the
`__ODYSSEY_NONCE__`/`__ODYSSEY_CSP__` placeholders `viewerPanel.ts`
substitutes (so those substitutions are harmless no-ops against the current
file), and the viewer's CDN-hosted Google Fonts + `motion` script tags will
be blocked by the strict CSP `viewerPanel.ts` sets (`default-src 'none'`
with no allowance for `fonts.googleapis.com` / `cdn.jsdelivr.net`). Expect a
visually broken (unstyled font, no animation library) but structurally
present viewer until the separate `spike/webview/` effort lands the
placeholder + CDN-localization refactor this host was written against.

## What could NOT be verified in the cloud sandbox and needs YOUR confirmation

- **The entire live path**: everything from step 5 onward that says "this
  is the first live network call" — no `query()` call has ever executed in
  this spike. `runLiveGenerate()` in `src/odysseyHost.ts` and its one call
  site in `src/extension.ts` were type-checked (`tsc --noEmit --strict`)
  against the real SDK types but never invoked. Confirm on your machine
  that: the native `claude` binary actually spawns and authenticates, the
  progress-message stream reads as expected in the output channel/progress
  notification, and a real `.odyssey/` bundle gets written.
- **Gemini-backed scene art + narration** (Generate mode specifically) — no
  Gemini call has been made anywhere in this spike.
- **F5 / Extension Development Host launch itself** — this cloud container
  has no VS Code GUI, so "does F5 actually work" is unverified. What IS
  verified: `tsc --noEmit --strict` passes, `esbuild` produces a loadable
  CJS `dist/extension.js`, and `vsce package` successfully packages the
  extension (`dist/prodyssey-host-spike.vsix`, 894 KB) without needing extra
  package.json fields beyond `--allow-missing-repository` (see FINDINGS.md
  section 5). None of that is a substitute for an actual F5 run.
- **`SecretStorage` prompt/persist round-trip** — the `context.secrets`
  get/prompt/store logic in `extension.ts` type-checks against
  `@types/vscode`'s `SecretStorage` interface but has never run inside a
  real extension host, so the actual VS Code keychain-backed persistence
  behavior (e.g. does it survive an Extension Development Host restart) is
  unconfirmed.
- **Prereq detection (`which uv` / `which python3`) on Windows** — the code
  branches to `where` on `process.platform === 'win32'`, but this was never
  exercised on a Windows machine.
- **The packaged `.vsix`'s actual runtime behavior.** Per FINDINGS.md 2a/5,
  the canonical `dist/prodyssey-host-spike.vsix` built with
  `--no-dependencies` is missing the native `claude` binary its own bundled
  JS needs to `spawn()` at runtime, so installing that exact `.vsix` and
  running any Prodyssey command would be expected to fail with "Native CLI
  binary ... not found" — confirm this failure mode yourself if you want to
  see it firsthand, and see FINDINGS.md for the two real fixes (ship the
  platform binary, or set `pathToClaudeCodeExecutable` to a system-installed
  `claude`).
