---
title: "Baseline Derivation — describe-lite reference"
type: reference
status: active
last_verified: 2026-07-20
owner: bjoerns
---

# Baseline Derivation — describe-lite reference

How to derive an architecture baseline for a foreign repo with zero existing
architecture docs: a district map plus a flat `inventory.yaml`, written into
`<target>/.odyssey/`. This is the *describe-lite* mode — it keeps the parent
skill's verification discipline (never assert an unverified boundary) but
drops the full per-context artifact set (`canvas.md`, `boundary.yaml`,
governed ADRs) that assumes you maintain the target repo.

## 1. Verification discipline — ground every claim in code

**Never write a district summary or boundary claim you have not checked.**
Before writing anything, run real commands against `<target>`:

```bash
# 1. Enumerate top-level structure
git -C <target> ls-files | cut -d/ -f1 | sort | uniq -c | sort -rn

# 2. Per candidate district: file count and rough size
find <target>/<dir> -type f | wc -l

# 3. Real outbound edges: what does this dir import from other top-level dirs?
grep -rhE "^(from|import) |require\(" <target>/<dir> | sort -u

# 4. Real inbound edges: who imports this dir?
grep -rl "<dir-name>" <target> --include="*.py" --include="*.ts" --include="*.tsx" | grep -v "^<target>/<dir>"
```

If you can't verify an import edge both directions, don't claim it — describe
the district by what it contains, not by a boundary relationship you haven't
checked.

## 2. Stack detection

Before clustering districts, match the repo against `references/stacks/`
using the detection precedence in `references/stacks/README.md`:

1. Evaluate cards most-specific first (framework before language — `nextjs`
   before `react-typescript`).
2. First card whose `## Detect` markers all match wins.
3. `generic.md` is the fallback.
4. Polyglot repos: load one card per matched sub-tree, scoped to that
   sub-tree (e.g. a FastAPI backend dir gets `python-fastapi.md`, a React
   frontend dir gets `react-typescript.md`).

Record the matched stack(s) — they inform the district `kind` classification
in §3 and give downstream story authoring (`story-mode.md`) the right
vocabulary for architectural weight.

## 3. District heuristic

1. **Candidate districts** = top-level dirs from `git -C <target> ls-files`
   with **≥3 tracked files**. Merge trivial dirs (config-only, single-file,
   `.github/`-style tooling shells) into a neighboring district or a catch-all
   `tooling` district rather than giving them their own entry.
2. **Classify `kind`** per district, one of: `core`, `tooling`, `quality`,
   `knowledge`, `product`, `governance`, `unknown`. Base the call on what the
   directory's files actually are (verified in §1), not the directory name
   alone — a `lib/` full of test fixtures is `quality`, not `core`.
3. **Claude authors** `label` (short, human-readable name — not the raw dir
   path) and a one-line `blurb` per district, grounded in the verified
   contents and import edges. Do not invent behavior the files don't show.
4. **Degrade honestly**:
   - Monorepos with package manifests scattered across many dirs: cluster at
     the manifest boundary (`package.json`, `pyproject.toml`, `go.mod`), cap
     at **≤12 districts** — merge the smallest into siblings if over.
   - Repos with **<20 tracked files total**: single district covering the
     whole repo.
   - Docs-only or asset-only repos (no code files matched by any stack card):
     bucket by file type (`docs`, `assets`, `config`) and set
     `map_quality: low` on the district-map output so downstream consumers
     know not to over-trust it.

## 4. Writing the outputs

### `world.districts` in `data/story.json`

Write each district directly into the `world.districts` array of
`story.json` (create the seed via `extract_story.py` first if `story.json`
doesn't exist yet — see SKILL.md Baseline mode step 1). Shape:

```json
{
  "id": "<slug>",
  "label": "<authored label>",
  "kind": "core|tooling|quality|knowledge|product|governance|unknown",
  "blurb": "<one-line, grounded in verified contents>",
  "root_paths": ["<dir>", "..."]
}
```

Never overwrite a district entry that already has human-authored fields (a
`blurb` that doesn't match the auto-generated pattern) — treat existing
non-placeholder text as authored and leave it, per the same discipline
`extract_story.py` applies to narrative fields.

### `<target>/.odyssey/inventory.yaml`

```yaml
generated: <ISO date>
provenance: inferred
contexts:
  - id: <slug>
    label: <authored label>
    paths: [<dir>, ...]
    summary: <one-line, grounded in verified contents>
```

`contexts[].id` matches `world.districts[].id` in `story.json` — this is the
join key `decision-records-lite.md`'s `maps_to` anchors against, and what ADR
retro-extraction cites when a decision affects a given district.

## 5. Surfacing smells (lite)

While verifying imports (§1) you may find real problems — circular
dependencies, a district importing something it clearly shouldn't. Do not
silently fold these into a clean-looking district blurb. Note them in the
district's `blurb` or as a short aside when authoring PR-level architecture
narrative (`story-mode.md` level 3) if a PR touches the smell — but do not
build a `boundary.yaml`, forbidden-dependency list, or SMELL-tagged rule
registry; that's full describe-mode machinery this lite mode doesn't carry.

## 6. When to re-run

Baseline is idempotent and safe to re-run any time; it refreshes districts
and inventory in place without touching per-PR narrative or ADR data. The
`generate` mode in SKILL.md warns when the baseline is more than 200 commits
behind `HEAD` — re-run baseline explicitly if that warning fires and the repo
has grown new top-level districts since.
