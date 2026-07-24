---
name: odyssey
title: "Codebase Odyssey Generator"
status: active
version: 0.1.0
description: >
  Generate a narrated four-level codebase story bundle (landscape, problem/solution,
  architecture, file-changes) with scene art, voice narration, and retro-extracted
  architecture decision records for any locally checked-out git repo. Also serves the
  bundle locally for viewing. Use when the user asks to "generate codebase odyssey",
  "generate story for PR", "odyssey baseline", "prodyssey", "narrated PR story", "tell
  the story of this PR as scene art", "explain this PR as a story", "build the odyssey
  bundle", "refresh odyssey baseline", "view the odyssey bundle", "serve the bundle",
  "open the viewer", "start the odyssey server", "stop the odyssey server", or invokes
  `/prodyssey:baseline`, `/prodyssey:generate`, or `/prodyssey:view`.
---

# Codebase Odyssey Generator

Orchestration procedure for turning merged PRs of **any locally checked-out git
repo** — the session's own repo, or any other checkout reached via `--repo` — into
a portable bundle: four-level narrated story, scene art, TTS narration, and ADR
retro-extraction. This is a read-only, generate-only instrument against the target
repo — it never edits the target repo's source, only writes into its bundle
directory (`<bundle-dir>`, see Hub resolution below).

Where that bundle actually lands depends on whether the target is the session's
own repo or a foreign one: self-analysis bundles stay at `<target>/.odyssey/`,
foreign-repo bundles are stored centrally at `<hub>/.prodyssey/<repo-slug>/`. See
Hub resolution below for the exact rule.

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
resolved path as `--repo <target>`; where the bundle actually lands (`<bundle-dir>`)
is determined by the storage rule in Hub resolution below, overridable with
`--store local|central`.

## Hub resolution

`<hub>` — the local scratch root for bookkeeping and for centrally-stored
bundles — is resolved the same way `<target>` falls back in step 2 above: the
git toplevel of the session's own working directory. `<hub>` is never affected
by `--repo`; it is always about the session's own checkout, not the repo being
analyzed.

**Storage rule** — where a given invocation's bundle actually lives:

- **Self-analysis** (no `--repo` given, or `--repo` resolves to the same repo
  as `<hub>` — i.e. `<target>`'s git toplevel equals `<hub>`): the bundle stays
  at `<target>/.odyssey/`, unchanged from today.
- **Foreign repo** (`--repo <other-path>` resolves to a DIFFERENT repo than
  `<hub>`): the bundle moves to `<hub>/.prodyssey/<repo-slug>/`.

An optional `--store local|central` flag overrides the automatic rule
regardless of the self/foreign check: `--store local` forces
`<target>/.odyssey/`, `--store central` forces `<hub>/.prodyssey/<repo-slug>/`.

Compute `<repo-slug>` once per invocation whenever the foreign path applies:

```bash
REMOTE=$(git -C "<target>" remote get-url origin 2>/dev/null)
NAME=$(basename "${REMOTE:-<target>}" .git)
NAME=$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//')
HASH=$(printf '%s' "<resolved-abs-target-path>" | shasum | cut -c1-8)
SLUG="${NAME}-${HASH}"
```

Then set `<bundle-dir>` once, at the top of every baseline/generate invocation:

```bash
STORE_MODE="<local|central, from --store if the user passed it, else empty>"
HUB_TOPLEVEL=$(git -C "<hub>" rev-parse --show-toplevel)
TARGET_TOPLEVEL=$(git -C "<target>" rev-parse --show-toplevel)

if [ "$STORE_MODE" = "local" ] || { [ "$STORE_MODE" != "central" ] && [ "$HUB_TOPLEVEL" = "$TARGET_TOPLEVEL" ]; }; then
  BUNDLE_DIR="<target>/.odyssey"
else
  BUNDLE_DIR="<hub>/.prodyssey/$SLUG"
fi
```

`<bundle-dir>` replaces every `<target>/.odyssey` reference in Baseline mode
and Generate mode's script invocations below.

Whenever `<bundle-dir>` resolves under `<hub>/.prodyssey/` (the central case,
whether reached automatically or via `--store central`) and
`<hub>/.prodyssey/` doesn't exist yet, create it (`mkdir -p`) and check
whether the hub's `.gitignore` already covers `.prodyssey/`; if not, print a
suggested line for the user to add manually — do NOT edit `.gitignore`
yourself. This applies the first time *any* mode (Baseline, Generate, or
View) creates the directory, not just View mode — and it's a one-time
notice, not a durable reminder: once `<hub>/.prodyssey/` exists, later
invocations skip the check even if the user never actually added the
suggested line.

## Step 0 — Prereq gate (hard, before ANYTHING generative)

Applies to **baseline** and **generate** modes. **View and Publish modes are
exempt** — View only serves static files already on disk (needs neither `uv`
nor `GEMINI_API_KEY`); Publish only flattens/publishes what's already
generated (needs `uv` for its export scripts, but not `GEMINI_API_KEY`). See
each mode's own section below.

Run this before any other step, every baseline/generate invocation:

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

The invoking command passes a mode (`baseline`, `generate`, `view`, or
`publish`) plus forwarded args (`--repo`, `--store`, `--prs`, `--force`,
`--voice`, `--dry-run`, `--port`, `--stop`, `--list`, `--format`). If invoked
with no mode, ask the user whether they want `baseline`, `generate`, `view`,
or `publish`.

## Baseline mode

Derives the repo's architecture baseline into `<bundle-dir>` (computed per Hub
resolution above). Follow `references/baseline-derivation.md` for the full
procedure. Summary:

1. Run the seed extraction:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/extract_story.py" --repo <target> --bundle-dir <bundle-dir> --dry-run
   ```
   (drop `--dry-run` once ready to write) — this creates `data/story.json` from
   `inventory.yaml` if `story.json` doesn't exist yet, and writes `data/story.js` +
   `data/manifest.js`.
2. Detect the stack(s) per `references/stacks/README.md` detection precedence
   (most-specific card first; `generic.md` fallback). Polyglot repos load one card
   per matched sub-tree.
3. Derive the district map and per-district summaries per
   `references/baseline-derivation.md`; author labels/kinds/blurbs directly into
   `world.districts` in `story.json`, and write `<bundle-dir>/inventory.yaml`.
4. Copy the viewer:
   ```bash
   cp "${CLAUDE_PLUGIN_ROOT}/viewer/index.html" <bundle-dir>/viewer/index.html
   ```
5. Verify:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/verify_bundle.py" --bundle-dir <bundle-dir> --json
   ```
   Report the `baseline` section of the result to the user.

Re-runnable any time; refreshes in place. Never overwrites human-authored narrative
fields already present in `story.json` (that discipline lives in `extract_story.py`
and in how you write district blurbs — treat existing text as authored, not
scratch).

## Generate mode

Per-PR narrative + ADR + art + audio sweep. Steps:

1. **Auto-baseline check**: if `<bundle-dir>/data/story.json` or
   `<bundle-dir>/inventory.yaml` is missing, announce "No baseline found —
   running baseline first" and execute the full Baseline mode above before
   continuing.
2. **Resolve the PR list**: use `--prs` if given (comma list, range `N..M`, or
   `--latest`). Otherwise let `extract_story.py`'s discovery surface the most
   recent PRs (merge commits → squash `(#N)` → `gh` fallback) and confirm the last
   10 with the user before proceeding.

   `--prs N` can resolve to either a merged commit or a currently-open PR (the
   `gh` fallback checks `mergedAt`/`mergeCommit` and, if both are empty, treats
   N as open — diffing against the local merge-base of its head and base
   branches instead of a merge/squash commit). Open-PR entries are tagged
   `"status": "open"` in `story.json` and reflect the PR's diff as of
   generation time, not settled history: re-running generate mode with `--force`
   for that PR after new commits land on its branch refreshes the
   size/touched/diff/narrative for the new tip, rather than treating the
   original snapshot as immutable the way a merged PR's is.


3. **Per PR**, run the resumability check first and only execute stages which
   artifacts are missing (or all stages if `--force`):
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/verify_bundle.py" --bundle-dir <bundle-dir> --prs <N> --json
   ```
   The result's `prs.<N>` map tells you, per artifact key, `"ok"` or `"missing"`.
   Execute only the missing stages, **in this order**:

   1. **Narrative authoring** (Claude work, not a script). Follow
      `references/story-mode.md`. Ground every claim by reading the diff (from
      `extract_diffs.py`'s output — run it first if the diff isn't extracted yet),
      the touched files in `<target>`, and `<bundle-dir>/inventory.yaml`.
      Author the four levels (`landscape`, `problem_solution`, `architecture`,
      `file_changes`), the tagline, and the `voice` scripts directly into
      `data/story.json` for this PR. **`problem_solution` and `architecture`
      each also need a `beats` array** (`{"kind": ..., "text": ...}` items) —
      this is what the viewer's Background/Intuition and Forces/Contract/
      Boundary cards actually render; `problem`/`solution`/`forces`/`decision`
      alone are not enough. See `references/story-mode.md` §2a for the exact
      `kind` values per level and worked guidance.
   2. **ADR retro-extraction**. Follow `references/decision-records-lite.md`.
      Write/update `data/adrs.json` and `data/adrs.js`, and set this PR's `adrs[]`
      array in `story.json` to the resulting record ids.
   3. **Diff extraction**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/extract_diffs.py" --repo <target> --bundle-dir <bundle-dir> --prs <N>
      ```
   4. **Scene-art prompts + generation**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_prompts.py" --repo <target> --bundle-dir <bundle-dir> --prs <N> --generate
      ```
   5. **Voice narration**:
      ```bash
      uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_audio.py" --repo <target> --bundle-dir <bundle-dir> --prs <N>
      ```
      Pass `--voice <V>` if the user specified one.

   `--force` regenerates every stage regardless of `verify_bundle.py`'s result.
4. **Final verify**: re-run `verify_bundle.py --prs <all-selected> --json` and
   report a per-PR artifact table (which stages ran, which were skipped as already
   complete, which failed).

## View mode

Serves the currently selected bundle's `viewer/` as a static site in the
background — the session keeps going, the user gets a URL to open. No Gemini
call, no `uv`, just `python3`'s stdlib `http.server`, bound to localhost only.

One long-lived server process per hub, rooted at `<hub>/.prodyssey/` itself
(never at a bundle's `viewer/` subfolder directly — see below), always serving
`http://localhost:<port>/active/viewer/`. Switching which bundle is being
viewed is just repointing a symlink; it never requires restarting the server.

**Why the server is rooted one level up.** `viewer/index.html` requests
`../data/story.js`, `../data/manifest.js`, etc — `data/` is a SIBLING of
`viewer/`, not a child of it. A server rooted directly at `<bundle-dir>/viewer/`
404s on every one of those requests. The server must be rooted at the bundle
ROOT (parent of `viewer/` and `data/`), and the reported/requested URL must
include the `/viewer/` path segment. (Confirmed via curl this session: 404
from `<bundle-dir>/viewer/` root; 200 once served from `<bundle-dir>` — the
bundle root — with `/viewer/index.html` requested.) `python3 -m http.server` also
correctly follows symlinks — both the symlink itself and the relative
`../data/...` requests made through pages served via the symlink resolve
correctly (confirmed via curl this session) — which is what makes the
one-server-plus-symlink design below work.

### Layout

`<hub>/.prodyssey/` holds:
- One subfolder per foreign-repo bundle: each `<repo-slug>/` is a full bundle
  root (`data/`, `viewer/`, `assets/`), created by Baseline/Generate mode per
  the storage rule in Hub resolution above.
- `active` — a symlink to the ABSOLUTE path of whichever bundle root is
  currently selected for viewing. Points either at a `<hub>/.prodyssey/<slug>/`
  entry, or at `<target>/.odyssey/` itself when viewing the hub's own
  self-analysis bundle.
- `.view-server.pid` / `.view-server.log` — the one long-lived server process
  for this hub.

Compute `<hub>` per Hub resolution above; `<hub>/.prodyssey/` may already exist
from a prior Baseline/Generate run (same `mkdir -p` + `.gitignore` check
applies — see Hub resolution).

### Steps

1. **Lightweight check**: confirm `python3` is on PATH.

2. **Discover known bundles** — needed for selection, `--list`, and the
   auto-select case:
   - Central entries: immediate children of `<hub>/.prodyssey/` that are real
     directories, NOT symlinks — e.g. `find <hub>/.prodyssey -mindepth 1 -maxdepth 1 -type d`
     (`-type d` without `-L` naturally excludes the `active` symlink even
     though it points at a directory; don't use a glob like `*/`, which
     follows symlinks and would wrongly include `active` as if it were its
     own bundle). Also excludes `.view-server.pid`/`.view-server.log` since
     those are files, not directories.
   - Plus, if `<hub>/.odyssey/` exists (the hub's own self-analysis bundle),
     include it too.
   - For each, read `data/story.json`'s `meta.repo` and `meta.generated`
     fields to build a human-readable label (repo name + generation date).
     Skip an entry whose `story.json` is missing or unreadable rather than
     failing discovery outright — note it as incomplete if listing.

3. **`--list`**: print the discovered list from step 2 (label + path per
   entry) and STOP — don't start or switch anything.

4. **`--stop`**: kill this hub's server and STOP — do not start a new one:
   ```bash
   PIDFILE="<hub>/.prodyssey/.view-server.pid"
   LOGFILE="<hub>/.prodyssey/.view-server.log"
   if [ -f "$PIDFILE" ] && ps -p "$(cat "$PIDFILE")" -o command= | grep -q "http.server"; then
     kill "$(cat "$PIDFILE")"
     echo "stopped"
   else
     echo "no server running for this hub"
   fi
   rm -f "$PIDFILE" "$LOGFILE"
   ```
   (PID/log files live under `<hub>/.prodyssey/`, not `/tmp` — `.prodyssey/`
   is understood as hub-local scratch now, never part of any committable
   bundle.)

5. **Select which bundle to view**:
   1. `--repo <path>` given → resolve it directly via the storage rule in Hub
      resolution above to that repo's bundle-dir. No prompt.
   2. No `--repo`, and step 2's discovery found exactly one bundle total →
      auto-select it. No prompt.
   3. No `--repo`, and discovery found multiple bundles → present the list
      from step 2 (label + date per entry) and use the `AskUserQuestion` tool
      to ask the user which one to view.
   4. No `--repo`, and discovery found zero bundles → tell the user to run
      `/prodyssey:baseline` first and STOP.

   Whichever bundle-dir is selected, confirm `data/story.json` and
   `viewer/index.html` exist under it before proceeding; if not, STOP and
   tell the user to run `/prodyssey:baseline` for that repo first (same
   remediation as 5.4 — this also covers the case where `--repo` pointed at
   a real repo that just hasn't been baselined yet, or was baselined with a
   different `--store` mode than the one this resolution assumed).

6. **Point `active` at the selection**:
   ```bash
   ln -sfn "<absolute-selected-bundle-dir>" "<hub>/.prodyssey/active"
   ```

7. **Reuse or start the server**:
   ```bash
   PIDFILE="<hub>/.prodyssey/.view-server.pid"
   LOGFILE="<hub>/.prodyssey/.view-server.log"
   REQUESTED_PORT="<value of --port if the user passed it, else 0 for an OS-assigned port>"
   if [ -f "$PIDFILE" ] && ps -p "$(cat "$PIDFILE")" -o command= | grep -q "http.server"; then
     RUNNING_PORT=$(grep -o "port [0-9]*" "$LOGFILE" | tail -1 | grep -o "[0-9]*")
     echo "already running on port $RUNNING_PORT — active bundle switched, just refresh the browser tab"
   else
     nohup python3 -u -m http.server "$REQUESTED_PORT" --bind 127.0.0.1 --directory "<hub>/.prodyssey" > "$LOGFILE" 2>&1 &
     echo $! > "$PIDFILE"
   fi
   ```
   If a server is already running for this hub, do NOT start a second one —
   repointing `active` (step 6) is enough; the running server picks up the new
   symlink target on its next request, no restart needed. Just report the
   existing port/URL and tell the user to refresh — note that `--port` has no
   effect in this branch (it only applies to a fresh start); if the user
   explicitly passed `--port` while a server is already running on a
   different port, tell them so rather than silently ignoring it. Run the
   start branch as a normal (non-backgrounded-tool-call) Bash invocation —
   the trailing shell `&` detaches the server process itself, so the tool
   call returns immediately with nothing left running in its own foreground.
   Do not use the Bash tool's own `run_in_background` option here; that's for
   commands that eventually finish, and this one never does.

8. **Confirm a fresh start actually came up** (skip this if step 7 reused an
   existing server): poll the log briefly rather than a single fixed sleep —
   `http.server` startup time varies under load:
   ```bash
   for i in 1 2 3 4 5 6 7 8 9 10; do
     grep -q "Serving HTTP" "$LOGFILE" 2>/dev/null && break
     sleep 0.3
   done
   cat "$LOGFILE"
   ```
   If a `Serving HTTP on ... port NNNNN ...` line appears, parse the port out
   of it. If it doesn't appear within the poll window — port collision
   (`--port <N>` pointed at something already listening), permission error,
   whatever — treat it as a failed start: show the log contents to the user
   verbatim and STOP. Never report a URL you haven't confirmed is live.

9. **Report the URL**: `http://localhost:<port>/active/viewer/`. Tell the
   user the server keeps running in the background — the session is free to
   continue — that switching bundles later is just re-running
   `/prodyssey:view --repo <other>` (or answering the picker) and refreshing
   the tab, and that `/prodyssey:view --stop` shuts the server down entirely.

## Publish mode

Flattens already-generated PRs into self-contained Claude Artifacts — one per
PR, plus an index artifact linking to all of them. Publish mode is a
consumer of an existing bundle, not a generator: it needs `uv` (to run the
export scripts) but not `GEMINI_API_KEY`, and doesn't touch `<target>` at all.

1. **Resolve `<bundle-dir>`** per Hub resolution above (same `--repo`/`--store`
   rules as every other mode — nothing new here).
2. **Resolve `--format`** (default `artifact`). Anything other than `artifact`
   — right now that's just `notion` — is a recognized, reserved value with no
   implementation yet: report that clearly ("`--format notion` isn't
   implemented yet") and STOP rather than falling through to the artifact
   path silently.
3. **Resolve the PR list** from `--prs` (comma list or `N..M` range, same
   parsing as Generate mode). For each requested PR, confirm it exists in
   `<bundle-dir>/data/story.json`'s timeline; if any don't, tell the user to
   run `/prodyssey:generate --prs <N>` first and STOP before publishing any
   of the others (a partial publish from a partially-valid PR list is more
   confusing than refusing up front).
4. **Per PR**, in order:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/export_artifact.py" --bundle-dir <bundle-dir> --prs <N>
   ```
   This writes `<bundle-dir>/exports/pr-<N>.html` and updates that PR's entry
   in `<bundle-dir>/exports/publish-manifest.json`, printing whether the
   commit or narrative content changed since the last export. Read
   `publish-manifest.json` after the script runs (it prints the path) to get
   this PR's current `artifact_url` (if any):
   - If there's no recorded `artifact_url` yet, or the script reported a
     commit/content change, or the user passed `--force`: call the `Artifact`
     tool on `exports/pr-<N>.html` (`title`: `"<repo> — PR #<N>: <title>"`,
     `description`: the PR's tagline, `favicon`: an emoji fitting the PR).
     Pass the existing `artifact_url` as `url:` when there is one, so
     republishing updates the same link instead of minting a new one. Then
     record the result:
     ```bash
     uv run "${CLAUDE_PLUGIN_ROOT}/scripts/record_publish.py" --bundle-dir <bundle-dir> --target pr-<N> --url <returned-url>
     ```
   - Otherwise, report "already up to date" with the existing URL and move on
     — don't call the Artifact tool for a PR that hasn't changed.
5. **Always rebuild and republish the index**, regardless of which PRs (if
   any) actually changed this run — it reflects every PR ever recorded in
   `publish-manifest.json`, not just this invocation's:
   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/export_index.py" --bundle-dir <bundle-dir>
   ```
   Call the `Artifact` tool on the resulting `exports/index.html`, passing
   `publish-manifest.json`'s `index.artifact_url` as `url:` when present so
   it updates in place across sessions the same way per-PR artifacts do.
   Record it the same way: `--target index`.
6. **Report a summary table** — PR, status (published / updated / unchanged),
   artifact URL — plus the index URL.

If the `Artifact` tool isn't available (per Anthropic's own documentation:
publishing artifacts requires a `/login` session on a paid plan — API-key and
cloud-provider-credential sessions can't publish), the export files this mode
produces are still valid deliverables — tell the user where they landed
(`<bundle-dir>/exports/`) so they can open or share them another way instead
of the run looking like it silently failed.

## Notes

- Narrative authoring and ADR extraction are Claude judgment work — never delegate
  their content to a script. Scripts only move data (diffs, prompts, audio, bundle
  verification).
- Never touch anything in `<target>` outside `<target>/.odyssey/` and `<target>/.env`
  (read-only check, never written by this skill) — `<hub>/.prodyssey/` is also a
  sanctioned write location, for centrally-stored bundles and view-server bookkeeping.
- `story.json`'s `meta.schema_version` is `"1.0"` — `verify_bundle.py` gates on it.
- View mode's PID/log files and the `active` symlink live under
  `<hub>/.prodyssey/`, never inside `<target>/.odyssey/` — that directory is the
  committable bundle when self-analysis storage applies.
- Publish mode's `exports/` (per-PR HTML, `index.html`, `publish-manifest.json`)
  lives inside `<bundle-dir>` and is committable the same way `data/`/`assets/`
  are — it's the durable record of what's been published and from what
  version, not disposable build output.
