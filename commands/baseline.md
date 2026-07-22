---
title: "Odyssey: Derive Baseline"
status: active
type: command
last_verified: 2026-07-20
---

# Odyssey: Derive Baseline

Derives (or refreshes) the current repo's architecture baseline into
`.odyssey/`: stack detection, district map, and `inventory.yaml`. Safe to
re-run any time.

Invoke the `odyssey` skill in baseline mode, forwarding any arguments the user
supplied after `/prodyssey:baseline` (e.g. `--force`, or `--repo <path>` to
target any local checkout other than the current session's repo):

```
Skill("odyssey", args="baseline $ARGUMENTS")
```

The target repo is the current working directory unless the user specifies
otherwise. The skill runs its own prereq gate (git repo, `uv` on PATH,
`GEMINI_API_KEY`) before doing anything — baseline mode itself doesn't call
Gemini, but the gate is unconditional per the skill's Step 0.

Where the bundle lands depends on what's being analyzed: self-analysis (no
`--repo`, or `--repo` pointing at this same repo) still stores it at
`<target>/.odyssey/` as before, while a foreign repo passed via `--repo`
stores it instead in a central per-hub cache
(`<hub>/.prodyssey/<repo-slug>/`) so foreign checkouts are never written
into. Pass `--store local` or `--store central` to override that automatic
choice.
