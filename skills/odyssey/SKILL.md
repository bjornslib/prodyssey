---
name: odyssey
title: "Codebase Odyssey Generator"
status: active
version: 0.1.0
description: >
  Generate a narrated four-level codebase story bundle (landscape, problem/solution,
  architecture, file-changes) with scene art, voice narration, and retro-extracted
  architecture decision records for any locally checked-out git repo. Use when the user
  asks to "generate codebase odyssey", "generate story for PR", "odyssey baseline",
  "prodyssey", "narrated PR story", "tell the story of this PR as scene art", "explain
  this PR as a story", "build the .odyssey bundle", "refresh odyssey baseline", or
  invokes `/prodyssey:baseline` or `/prodyssey:generate`.
---

# Codebase Odyssey Generator

Orchestration procedure for turning merged PRs of a target repo into a portable
`.odyssey/` bundle: four-level narrated story, scene art, TTS narration, and ADR
retro-extraction. This is a read-only, generate-only instrument against a foreign
repo — it never edits the target repo's source, only writes into `.odyssey/`.

Reference material lives in `references/` and is loaded on demand, not inlined here.
Scripts live in `scripts/` and are called via `uv run`, never edited by the skill.

## Target resolution

`<target>` — the repo being analyzed — is resolved in this order:

1. An explicit `--repo <path>` argument forwarded by the command. This may be ANY
   local checkout, not just the repo the session is running in (e.g.
   `/prodyssey:generate --repo ~/code/other-project --prs 12`).
2. Otherwise: the git toplevel of the session's working directory.

When `--repo` points outside the session's working directory, narrative authoring
requires read access to that path. If reads are being denied, tell the user to run
`/add-dir <path>` (or add the path to their permissions) and retry — do not work
around it by guessing at file contents. All script invocations below pass the
resolved path as `--repo <target>`; the bundle always lands at `<target>/.odyssey/`
unless the user overrides `--bundle-dir`.

## Step 0 — Prereq gate (hard, before ANYTHING generative)

Run this before any other step, every invocation:

1. Confirm `<target>` is a git repo: `git -C <target> rev-parse --is-inside-work-tree`.
   If it fails, STOP — this is not a git checkout.
2. Confirm `uv` is on PATH (`which uv`). If missing, STOP and tell the user to install
   `uv` (https://docs.astral.sh/uv/getting-started/installation/).
3. Confirm `GEMINI_API_KEY` is available: check the environment, then check for a
   `.env` file in `<target>` containing `GEMINI_API_KEY=`. If **neither** is present,
   STOP before running any script and print:

   ```
   GEMINI_API_KEY is required for scene art and voice narration.
   Get one at https://aistudio.google.com/apikey, then either:
     export GEMINI_API_KEY=<key>
   or add it to <target>/.env:
     GEMINI_API_KEY=<key>
   ```

   Do not run `generate_prompts.py --generate` or `generate_audio.py` without a
   confirmed key — narrative authoring and ADR extraction (which don't call Gemini)
   may still proceed if the user explicitly asks for text-only output, but the
   default `generate` sweep always needs the key and must stop here if absent.

Only after all three checks pass does mode dispatch begin.

## Mode dispatch

The invoking command passes a mode (`baseline` or `generate`) plus forwarded args
(`--prs`, `--force`, `--voice`, `--dry-run`). If invoked with no mode, ask the user
whether they want `baseline` or `generate`.

## Baseline mode

Derives the repo's architecture baseline into `<target>/.odyssey/`. Follow
`references/baseline-derivation.md` for the full procedure. Summary:

1. Run the seed extraction:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/extract_story.py" --repo <target> --bundle-dir <target>/.odyssey --dry-run
   ```
   (drop `--dry-run` once ready to write) — this creates `data/story.json` from
   `inventory.yaml` if `story.json` doesn't exist yet, and writes `data/story.js` +
   `data/manifest.js`.
2. Detect the stack(s) per `references/stacks/README.md` detection precedence
   (most-specific card first; `generic.md` fallback). Polyglot repos load one card
   per matched sub-tree.
3. Derive the district map and per-district summaries per
   `references/baseline-derivation.md`; author labels/kinds/blurbs directly into
   `world.districts` in `story.json`, and write `<target>/.odyssey/inventory.yaml`.
4. Copy the viewer:
   ```bash
   cp "${CLAUDE_PLUGIN_ROOT}/viewer/index.html" <target>/.odyssey/viewer/index.html
   ```
5. Verify:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/verify_bundle.py" --bundle-dir <target>/.odyssey --json
   ```
   Report the `baseline` section of the result to the user.

Re-runnable any time; refreshes in place. Never overwrites human-authored narrative
fields already present in `story.json` (that discipline lives in `extract_story.py`
and in how you write district blurbs — treat existing text as authored, not
scratch).

## Generate mode

Per-PR narrative + ADR + art + audio sweep. Steps:

1. **Auto-baseline check**: if `<target>/.odyssey/data/story.json` or
   `<target>/.odyssey/inventory.yaml` is missing, announce "No baseline found —
   running baseline first" and execute the full Baseline mode above before
   continuing.
2. **Resolve the PR list**: use `--prs` if given (comma list, range `N..M`, or
   `--latest`). Otherwise let `extract_story.py`'s discovery surface the most
   recent PRs (merge commits → squash `(#N)` → `gh` fallback) and confirm the last
   10 with the user before proceeding.
3. **Per PR**, run the resumability check first and only execute stages whose
   artifacts are missing (or all stages if `--force`):
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/verify_bundle.py" --bundle-dir <target>/.odyssey --prs <N> --json
   ```
   The result's `prs.<N>` map tells you, per artifact key, `"ok"` or `"missing"`.
   Execute only the missing stages, **in this order**:

   1. **Narrative authoring** (Claude work, not a script). Follow
      `references/story-mode.md`. Ground every claim by reading the diff (from
      `extract_diffs.py`'s output — run it first if the diff isn't extracted yet),
      the touched files in `<target>`, and `<target>/.odyssey/inventory.yaml`.
      Author the four levels (`landscape`, `problem_solution`, `architecture`,
      `file_changes`), the tagline, and the `voice` scripts directly into
      `data/story.json` for this PR.
   2. **ADR retro-extraction**. Follow `references/decision-records-lite.md`.
      Write/update `data/adrs.json` and `data/adrs.js`, and set this PR's `adrs[]`
      array in `story.json` to the resulting record ids.
   3. **Diff extraction**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/extract_diffs.py" --repo <target> --bundle-dir <target>/.odyssey --prs <N>
      ```
   4. **Scene-art prompts + generation**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_prompts.py" --repo <target> --bundle-dir <target>/.odyssey --prs <N> --generate
      ```
   5. **Voice narration**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_audio.py" --repo <target> --bundle-dir <target>/.odyssey --prs <N>
      ```
      Pass `--voice <V>` if the user specified one.

   `--force` regenerates every stage regardless of `verify_bundle.py`'s result.
4. **Final verify**: re-run `verify_bundle.py --prs <all-selected> --json` and
   report a per-PR artifact table (which stages ran, which were skipped as already
   complete, which failed).

## Notes

- Narrative authoring and ADR extraction are Claude judgment work — never delegate
  their content to a script. Scripts only move data (diffs, prompts, audio, bundle
  verification).
- Never touch anything in `<target>` outside `<target>/.odyssey/` and `<target>/.env`
  (read-only check, never written by this skill).
- `story.json`'s `meta.schema_version` is `"1.0"` — `verify_bundle.py` gates on it.
