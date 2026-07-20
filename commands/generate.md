---
title: "Odyssey: Generate PR Stories"
status: active
type: command
last_verified: 2026-07-20
---

# Odyssey: Generate PR Stories

Runs the full per-PR sweep — narrative, ADR retro-extraction, scene art, and
voice narration — into `.odyssey/`. If no baseline exists yet, one is derived
automatically first.

Invoke the `odyssey` skill in generate mode, forwarding any arguments the user
supplied after `/prodyssey:generate` (`--prs`, `--latest`, `--force`,
`--voice`):

```
Skill("odyssey", args="generate $ARGUMENTS")
```

## Default PR selection

If the user doesn't pass `--prs`, `--latest`, or a range (`N..M`), the skill
discovers PRs via merge commits / squash `(#N)` markers (falling back to `gh`
if needed), proposes the **last 10 discovered PRs**, and confirms the list
with the user before running anything — it never silently sweeps an
unconfirmed PR list.

## Examples

```
/prodyssey:generate --prs 73,75
/prodyssey:generate --latest
/prodyssey:generate --prs 12..18
/prodyssey:generate --force
```
