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
supplied after `/prodyssey:baseline` (e.g. `--force`):

```
Skill("odyssey", args="baseline $ARGUMENTS")
```

The target repo is the current working directory unless the user specifies
otherwise. The skill runs its own prereq gate (git repo, `uv` on PATH,
`GEMINI_API_KEY`) before doing anything — baseline mode itself doesn't call
Gemini, but the gate is unconditional per the skill's Step 0.
