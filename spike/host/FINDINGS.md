# Prodyssey VS Code extension spike — host / SDK findings

Scope: `spike/host/` only; the repo outside `spike/` is untouched. Every claim
below was read directly from the installed
`node_modules/@anthropic-ai/claude-agent-sdk` (v0.3.218) — its `package.json`,
shipped `.d.ts`, and minified `sdk.mjs` — and independently re-verified by the
main agent (not just asserted by the builder). No live Anthropic or Gemini API
call was made; all findings are static inspection + offline builds.

---

## TL;DR — the one finding that changes the plan

**`query()` does NOT run in-process. It spawns a ~260 MB native `claude` CLI
binary as a child process.** That binary is not part of the 4.1 MB core npm
package — it ships as a separate, per-platform optional dependency
(`@anthropic-ai/claude-agent-sdk-<os>-<arch>`), one per platform, each
~255–274 MB. Consequence for "bundle everything in one `.vsix`":

- Packaging WITH dependencies → **~170 MB `.vsix` per platform** (measured).
- Packaging WITHOUT dependencies (esbuild inlines the SDK's JS) → **~900 KB
  `.vsix` that throws at runtime** (`Native CLI binary … not found`), because
  esbuild can bundle the SDK's JavaScript but not the native binary it
  `spawn()`s.

So "install one extension, everything included" is still achievable, but it
means **a per-platform ~150–180 MB `.vsix`** (VS Code supports per-target
publishing), OR **requiring the user to have the `claude` CLI installed** and
pointing at it via `options.pathToClaudeCodeExecutable`. This is the single
biggest de-risking result of the spike and belongs front-and-center in the
distribution decision.

---

## Runtime footprint (verified)

| item | value |
|---|---|
| core `@anthropic-ai/claude-agent-sdk` | v0.3.218, `main: sdk.mjs` (ESM), `engines.node >=18`, **no `bin`** |
| platform binary (`…-linux-x64/claude`) | **261 MB, ELF 64-bit executable**, runs standalone (needs no Node) |
| platform packages declared | **8** (linux x64/arm64 × glibc/musl, darwin x64/arm64, win32 x64/arm64) |
| `@anthropic-ai/` total in this container | 531 MB (two linux-x64 variants present) |
| full `spike/host/node_modules` | 728 MB |

How `query()` finds & runs the binary (traced in `sdk.mjs`, 47 `spawn`
references + `from "child_process"`): absent an explicit
`options.pathToClaudeCodeExecutable`, it does
`createRequire(<sdk.mjs path>).resolve('@anthropic-ai/claude-agent-sdk-<platform>/claude')`
then `child_process.spawn`s it. If the platform package isn't resolvable from
the SDK's install location, `query()` throws before doing anything. esbuild
bundling `sdk.mjs` into `dist/extension.js` does **not** remove this dependency.

**Packaging paths forward (pick in the distribution decision):**
1. Per-platform `.vsix` that ships the matching ~260 MB binary (~150–180 MB each).
2. Ship no binary; require `claude` installed on the host and set
   `pathToClaudeCodeExecutable` (adds an external prereq beyond `uv`/`python3`).
3. Hybrid: detect an existing `claude`, download the platform binary on first
   run if absent (keeps the `.vsix` small, adds a first-run download step).

---

## Auth (verified)

- **No programmatic `apiKey`/`authToken` input** on `Options`. The only
  auth-adjacent input is `pathToClaudeCodeExecutable` (binary path) and
  `Settings.apiKeyHelper` (path to a script that emits a token).
- Auth is env-var only, on the spawned subprocess. Recognized:
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and **`CLAUDE_CODE_OAUTH_TOKEN`**
  (all present in `sdk.mjs`).
- **`CLAUDE_CODE_OAUTH_TOKEN` is first-class** → a user logged in via
  `claude login` (Pro/Max subscription) needs **no API key at all**; the
  spawned binary reuses its own persisted credentials. Strong adoption lever.
- **`env` REPLACES the subprocess environment, it does not merge.** The host
  must spread `process.env` itself (else `PATH`/`HOME` are stripped and
  `uv run`/`git` break). `odysseyHost.buildEnv()` does this.
- `GEMINI_API_KEY` is not an SDK concept — it's read directly by the bundled
  odyssey skill's Python scripts; the SDK's `env` is just the delivery channel.

---

## `query()` option shapes — deltas from the original plan

| plan assumption | verified reality |
|---|---|
| plugin entry `{ path }` | **`{ type: 'local', path, skipMcpDiscovery? }`** — `type` required |
| `allowedTools: ['Read','Grep','Glob','Bash']` sufficient | **Insufficient — see gap below** |
| `canUseTool` returns bool/loose object | Discriminated union: `{behavior:'allow',…} \| {behavior:'deny',message,…}` (bare `null` reserved for out-of-band) |
| enable skills | `skills: ['odyssey']` is the sole switch — do NOT also add `'Skill'` to `allowedTools` (deprecated) |

Other confirmed options match the plan: `cwd`, `systemPrompt` (string | preset
object), `settingSources`, `permissionMode`, `mcpServers`, `model`.

---

## Material functional gap — sanctioned tool surface is too narrow

The plan's auto-approve surface (`Read`/`Grep`/`Glob`/`Bash`) is **not enough
for the real skill to work**. `SKILL.md`'s Generate mode authors the narrative
"directly into `data/story.json`" and writes/updates `data/adrs.json` /
`data/adrs.js` — that is **`Write`/`Edit` tool usage**, which this spike's
`canUseTool` denies by default. The spike implements the four-tool surface
exactly as the plan specified (deny-by-default, flagged in code), but a real
build-out must extend `allowedTools` + `canUseTool` to permit `Write`/`Edit`
**scoped to the bundle dir** (`<target>/.odyssey/` or `<hub>/.prodyssey/…`) so
the model can author bundle JSON while still being blocked from editing the
target repo's own source. This is the key correctness fix for the next phase.

---

## Verification results (re-run by the main agent)

- `npx tsc --noEmit --strict` → **exit 0** (against real SDK types).
- `node scripts/copy-plugin.mjs` → `spike/host/plugin/` (288 KB): `.claude-plugin/`,
  `skills/odyssey/` (+ references), `scripts/*.py`, `viewer/index.html` — the
  "bundle the plugin inside the extension" step, one source of truth.
- esbuild → `dist/extension.js` (1.3 MB, `vscode` external).
- `vsce package --no-dependencies` → `dist/prodyssey-host-spike.vsix` (~900 KB) —
  the "excludes the native binary, would fail at runtime" artifact.
- `vsce package` (with deps) → ~170 MB `.vsix` (measured, then deleted).

---

## Integration seam with `spike/webview/`

`src/viewerPanel.ts` is written to the webview contract: it substitutes a nonce
into `__ODYSSEY_NONCE__` and a strict CSP into `__ODYSSEY_CSP__`, and rewrites
`../data/`, `data/audio/`, `assets/` references to `webview.asWebviewUri(...)`.
Those placeholders + localized (non-CDN) deps are produced by the
`spike/webview/` effort (committed separately, render-proven). The two halves
meet exactly at this contract; `viewerPanel.ts` is the host side of it. Not yet
verified end-to-end inside a real webview (the `vscode-webview://` origin vs.
the render test's `http://localhost`) — that's the local F5 test in RUNBOOK.md.

---

## Deliverables

- `src/odysseyHost.ts` — `query()` options builder, `canUseTool`, progress mapper,
  guarded (never-invoked) live-call function.
- `src/extension.ts` — `activate()`, 3 commands, SecretStorage keys, prereq check,
  `withProgress`/OutputChannel wiring.
- `src/viewerPanel.ts` — webview panel, CSP/nonce substitution, asset URI rewrite.
- `scripts/copy-plugin.mjs`, `esbuild.config.mjs`, `tsconfig.json`, `package.json`.
- `RUNBOOK.md` — local F5 test procedure (what the cloud could not verify).
