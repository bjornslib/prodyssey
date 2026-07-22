---
title: "Odyssey: Publish PR Stories"
status: active
type: command
last_verified: 2026-07-22
---

# Odyssey: Publish PR Stories

Flattens already-generated PRs into self-contained Claude Artifacts — one per
PR, plus an auto-updating index artifact linking to every PR published so far
for this bundle.

Invoke the `odyssey` skill in publish mode, forwarding any arguments the user
supplied after `/prodyssey:publish` (`--repo <path>`, `--store local|central`,
`--prs`, `--format`, `--force`):

```
Skill("odyssey", args="publish $ARGUMENTS")
```

## Requirements

- The PR(s) must already exist in the bundle's `data/story.json` — run
  `/prodyssey:generate --prs <N>` first if not.
- Publishing needs the `Artifact` tool, which requires a `/login` session on
  a paid plan (Pro/Max/Team/Enterprise) — not an API-key or cloud-credential
  session. If it's unavailable, the flattened export files are still written
  to `<bundle-dir>/exports/` and usable another way.
- No `GEMINI_API_KEY` needed — publish mode only repackages what
  baseline/generate already produced.

## Formats

`--format artifact` (default) is the only implemented target today.
`--format notion` is accepted but not yet implemented — the skill reports
that clearly rather than silently publishing as an artifact instead.

## Staleness

Re-running `/prodyssey:publish` for a PR that hasn't changed since its last
publish reports "already up to date" and skips re-publishing it — no wasted
Artifact calls. A PR is considered changed if its underlying commit moved
(new commits landed on an open PR) or its narrative/ADR content was
re-authored at the same commit. `--force` republishes regardless.

## Examples

```
/prodyssey:publish --prs 73
/prodyssey:publish --prs 73,75
/prodyssey:publish --prs 73 --force
/prodyssey:publish --repo ~/code/other-project --prs 12
```
