---
title: "Stack Cards — Module Contract"
status: active
type: reference
last_verified: 2026-07-16
grade: authoritative
---

# Stack Cards — Module Contract

Per-technology reference cards that make stack detection deterministic and stack-specific
guidance explicit. Modes consult the matching card instead of guessing "based on detected
codebase". Pattern adapted from the `emadd/mise` stack-module contract, rescoped to
architecture concerns (no bootstrap content: gitignore, CLI tools, and connectors are
out of scope here).

## Card Fields

Every card is a markdown file with these sections:

| Section | Purpose | Consumed by |
|---|---|---|
| `## Detect` | Deterministic manifest/dependency markers | all modes — run first |
| `## Reference Structure` | Canonical layout with the rationale for each boundary | design (starting skeleton), review (diff target) |
| `## Boundary Rules` | Grep-checkable layering rules | review findings; seeds `boundary.yaml` `forbidden_dependencies` candidates in describe mode |
| `## Corpus Load` | Explicit corpus files this stack pulls in | design/review/maintenance corpus chains |
| `## Review Checks` | Stack-specific smells beyond the generic corpus | review/maintenance |
| `## ADR Topics` | Decisions this stack typically forces | decisions mode — checklist for made-but-unrecorded decisions |

Optional field: `## Inherits` — the card extends another card; load the parent card first,
then apply this card's sections as additions/overrides.

## Detection Precedence

1. Evaluate cards most-specific first: framework cards before language cards
   (`nextjs` before `react-typescript`).
2. First card whose `## Detect` markers all match wins.
3. If nothing matches, use `generic.md`.
4. Polyglot repos (e.g. FastAPI backend + React frontend): load one card per matched
   sub-tree, scoped to that sub-tree.

## STUB Convention

Partial cards are valid and expected — a card with only `## Detect` filled in still
improves routing. Mark incomplete cards with `status: draft` frontmatter and a
`> STUB` blockquote under the title. Deepening a stub (or adding a new stack) is a
single-file change.

## Current Cards

| Card | State |
|---|---|
| `python-fastapi.md` | fleshed out |
| `react-typescript.md` | fleshed out |
| `nextjs.md` | STUB |
| `generic.md` | fallback — always applicable |
