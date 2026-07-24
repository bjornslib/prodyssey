# CLAUDE.md

Guidance for Claude Code instances working in this repo.

## What this repo is

**prodyssey** is a Claude Code plugin (`.claude-plugin/`), not an app with a
build/test/deploy cycle. It has one job: turn merged PRs of *any* locally
checked-out git repo — the session's own repo, or any other checkout reached
via `--repo` — into a four-level narrated "codebase odyssey" — scene art,
voice narration, retro-extracted ADRs — viewable in a portable HTML viewer.

Where the bundle lands depends on the target: analyzing your own repo
(no `--repo`, or `--repo` resolving to the session's own checkout) writes to
`<target>/.odyssey/`; analyzing a foreign repo writes instead to
`<hub>/.prodyssey/<repo-slug>/`, where `<hub>` is the session's own repo —
never the foreign one. `--store local|central` overrides the automatic
choice. See `skills/odyssey/SKILL.md`'s Hub resolution section for the exact
rule and slug derivation.

Install surface: `/plugin marketplace add bjornslib/prodyssey` then
`/plugin install prodyssey@prodyssey`. No agents, no hooks, no MCP servers —
deliberate, so the plugin never touches another session's permission surface.

See `README.md` for the user-facing install/usage doc and the extraction
manifest (what was ported from `architecture-review-design-maintenance` and
what was deliberately left behind). Don't duplicate that content here —
this file is for orientation and things a future coding session needs to
know that aren't obvious from reading the files.

## Layout

```
.claude-plugin/       plugin.json (manifest) + marketplace.json
commands/              thin dispatchers: baseline.md, generate.md, view.md → Skill("odyssey", args=...)
skills/odyssey/
  SKILL.md            orchestration: prereq gate → baseline → per-PR sweep → verify
  references/         loaded on demand (story-mode, decision-records-lite,
                       baseline-derivation, adr-template, stacks/*)
  scripts/            5 PEP-723 uv scripts, called by the skill, never edited by it:
                       extract_story.py, generate_prompts.py, generate_audio.py,
                       extract_diffs.py, verify_bundle.py
viewer/index.html      the bundle viewer (~2000 lines, single file, see below)
```

`skills/` and `commands/` are auto-discovered — the manifest doesn't
declare them.

## How generation actually runs

`SKILL.md` is the source of truth for the procedure; skim it before changing
orchestration behavior. In short: a hard prereq gate (git repo, `uv` on PATH,
`GEMINI_API_KEY`) runs before anything generative; `baseline` mode derives
`.odyssey/inventory.yaml` + world districts; `generate` mode is per-PR and
resumable — `verify_bundle.py` decides which stages are already `"ok"` so a
killed sweep can be re-invoked without regenerating completed narrative,
art, or audio (`--force` overrides).

Narrative authoring and ADR extraction are **Claude judgment work** done
directly against `data/story.json` / `data/adrs.json` — never delegated to a
script. Scripts only move data: diffs, image prompts, audio, verification.

Scripts are PEP 723 (`uv run script.py` resolves `google-genai`, `pillow`,
`python-dotenv` inline — no venv, no `requirements.txt`).

## The viewer is not self-contained — this matters for anything artifact-related

`viewer/index.html` is a normal multi-file web page in disguise: one HTML
file, but it depends on three things that only exist *next to* it inside a
real `.odyssey/` bundle:

1. **Sibling `<script src="../data/*.js">` tags** (`story.js`, `manifest.js`,
   per-PR `diffs-pr{N}.js` via `document.write`, `adrs.js`) — this is how
   `window.STORY` / `window.ODYSSEY` / `window.DIFFS` / `window.ADRS` get
   populated. No inline data anywhere.
2. **Relative asset paths** — hero images at `../assets/pr-{N}/level-{L}.png`
   (built in `heroFrame()` and the audio-dialog image, both in
   `viewer/index.html`), narration audio at `../data/audio/pr{N}_{level}.wav`
   (`toggleAudio()`).
3. **Two external CDN requests** — Google Fonts (JetBrains Mono) and
   `cdn.jsdelivr.net/npm/motion` for the UI's micro-animations.

Intended viewing is `python3 -m http.server` inside `.odyssey/viewer/`, or
the (future) production app's *Import bundle* flow — both preserve the
relative file layout the viewer expects.

**This means the viewer cannot be published as a Claude Artifact as-is.**
Artifacts are a single self-contained file with no sibling files and a CSP
that blocks all external requests (fonts, scripts, fetch/XHR). Verified
2026-07-22 by building a throwaway artifact-safe export (inlined
`window.STORY`/`ODYSSEY`/`DIFFS`/`ADRS` as literal JSON, asset/audio paths
rewritten to look up a `window.ODYSSEY_ASSETS` / `window.ODYSSEY_AUDIO`
data-URI map instead of relative paths, both CDN tags dropped) and
publishing it — **it rendered correctly**, PR nav/levels/hero
image/audio dialog all worked. Two things fell out of that experiment worth
knowing if this gets revisited:

- The Motion CDN script already has a graceful no-op fallback
  (`if (!el || !window.Motion) return {finished: Promise.resolve()}` in
  `anim()`) — dropping it costs micro-animations, not correctness. Google
  Fonts failing just falls back to the existing `monospace`/`sans-serif`
  stack in the font declarations.
- The 16 MiB artifact size cap is the real constraint for a multi-PR bundle,
  and audio is what blows it — uncompressed WAV narration inflates ~33%
  again as base64. An artifact-export mode would need to either drop audio,
  transcode to a compressed format, or cap it to one PR/level at a time.

No such export mode exists in this repo yet — the experiment above was
scratch work to answer the feasibility question, not a shipped feature.
If someone asks for it, the shape is: a new script (or a flag on an existing
one) that reads a built `.odyssey/` bundle and emits one flattened HTML file
per the transform above.

## Bundle output shape (what generation produces)

```
<bundle-dir>/       <target>/.odyssey/ for self-analysis, <hub>/.prodyssey/<repo-slug>/ for a foreign repo
  data/{story.json, story.js, adrs.json, adrs.js, manifest.js,
        diffs-pr{N}.js…, audio/pr{N}_{level}.wav}
  assets/pr-{N}/level-{1..3}.png
  inventory.yaml
  viewer/index.html
```

`story.json`'s `meta.schema_version` is currently `"1.0"` —
`verify_bundle.py` gates on it (`SCHEMA_VERSION_KNOWN`). Both `.odyssey/` and
`.prodyssey/` are committed in *this* repo (not gitignored — `.odyssey/` was
explicitly un-ignored in `66782c7`, and `.prodyssey/` was never ignored):
`.odyssey/` is this repo's own generated bundle, tracked so engineers can
review each other's PRs as an odyssey instead of only a raw diff, same as
it's meant to be committed in target repos that adopt the plugin;
`.prodyssey/` holds committed *test fixtures* — bundles generated against
other local repos (`cobuilder-harness-a103a550`, `digital-curator-80f83abb`)
via `--repo`, kept as demo/dogfooding data rather than as this repo's own PR
history. A hub adopting the plugin for its own use is not expected to commit
`.prodyssey/` the same way — `skills/odyssey/SKILL.md`'s Hub resolution
section has the skill suggest a `.gitignore` line for it by default.

## Conventions worth preserving

- Never touch anything in `<target>` outside `<target>/.odyssey/` and a
  read-only check of `<target>/.env`; `<hub>/.prodyssey/` is also a
  sanctioned write location, for centrally-stored foreign-repo bundles and
  view-server bookkeeping.
- `extract_story.py` never overwrites authored narrative fields for PRs
  already in `story.json` — new PRs get a minimal stub; re-running is safe.
- `--repo <path>` (skill + all three commands) targets any local checkout,
  not just the session's own working directory; where the bundle lands is
  the Hub resolution storage rule — `<target>/.odyssey/` for self-analysis,
  `<hub>/.prodyssey/<repo-slug>/` for a foreign repo, overridable with
  `--store local|central`.
- Everything judgment-shaped (narrative voice, register, what counts as a
  decision worth an ADR) lives in `references/*.md` prose, loaded on demand
  — not hardcoded in scripts or the skill body.

## Recent history

Plugin scaffold → viewer port → skill/references/commands → generation +
verification scripts → `--repo` external-checkout targeting → Hub
resolution / central storage (`--store`, `.prodyssey/`, `view` command) (see
`git log` for the WS-A/B/C/D workstream commits). No test suite, no CI
config, no package manager — this is prose + Python scripts + one HTML file.
