---
title: "Decision Records (lite) — retro-extraction reference"
type: reference
status: active
last_verified: 2026-07-20
owner: bjoerns
---

# Decision Records (lite) — retro-extraction reference

How to retro-extract architecture decision records from a merged PR into the
Odyssey bundle's `data/adrs.json`. This is a *lite* form of the ISO/IEC/IEEE
42010 decision-record model (van Heesch, Avgeriou & Hilliard 2011) — governance
machinery (state transitions, human approval, viewpoint regeneration, ADR
numbering authority) is dropped because these records describe a foreign repo's
history, not a document set this plugin maintains. Start every record from
`references/adr-template.md`.

## 1. Record shape

One JSON object per decision, keyed by id in `data/adrs.json`:

```json
{
  "id": "ADR-0001",
  "title": "<one-line decision name>",
  "state": "approved",
  "source_pr": 73,
  "problem": "<the problem this decision answers>",
  "decision": "<the chosen option, one sentence>",
  "alternatives": [
    {"option": "<rejected option>", "rejected_because": "<why>"}
  ],
  "forces": ["<constraint/driver>", "..."],
  "delivers": {
    "capability": "<what is now possible that was not before>",
    "benefit": "<the value created and why it matters>",
    "beneficiary": ["operator", "developer"]
  },
  "body": "<markdown: Context / Options considered / Decision / Consequences / Value delivered / Maps to>"
}
```

`data/adrs.js` mirrors the same data as a browser-loadable global:
`window.ADRS = {<id>: <record>, ...};` — regenerate it alongside `adrs.json`
whenever a record changes; it is not hand-maintained.

`id` is `ADR-NNNN`, zero-padded, next free number across the whole bundle (not
per-PR) — read the existing `data/adrs.json` before picking the next id.

## 2. The value facet (`delivers`) — mandatory

Every record states the return, not only the cost. `capability` is what's now
possible that wasn't before; `benefit` is why that matters; `beneficiary` is
who gains (`operator | developer | validator-agent | the-business`, or repo-
appropriate equivalents). Mirror this in the body's `## Value delivered`
section.

## 3. Integrity rules (kept from the full model, non-negotiable)

1. **Never invent history.** These are retro-extractions from a repo you don't
   own — you only know the merge date, not internal deliberation. Do not
   fabricate a decision date beyond what `git log` gives you for the merge
   commit.
2. **`state: approved` for merged PRs.** A PR that shipped is, by definition,
   an approved decision at the point it merged — no separate human-approval
   step exists in this lite model (that machinery is dropped). Set
   `source_pr` and note in the body that the record is retroactively
   extracted.
3. **One record per structural decision** — module boundary, dependency
   direction, data-flow choice, public interface, cross-cutting pattern.
   Not every PR produces one; most PRs produce zero or one. Do not manufacture
   a record for a PR with no real structural decision.
4. **`alternatives` must be real.** Pull rejected options from the PR body,
   commit messages, or code comments — never invent an option the PR didn't
   actually consider. If you can't find any, either the PR isn't ADR-worthy or
   the alternative is genuinely just "do nothing," which is a legitimate
   entry.
5. **Examples never live in the register.** Sample/demo records belong in this
   reference file, not in a real bundle's `data/adrs.json`.

## 4. What's dropped from the full model, and why

| Dropped | Why |
|---|---|
| State machine (`idea → tentative → decided → approved → ...`) | Records are extracted post-merge; there is exactly one meaningful state (`approved`) for this plugin's purpose. |
| `approved_by` / human-approval gate | No human review loop exists for a generated bundle — the PR merge itself is the approval signal. |
| Viewpoint files (`relationship.md`, `chronology.md`, `capabilities.md`) | Those regenerate a maintained doc set; the bundle's `adrs.json`/`adrs.js` *is* the artifact. |
| ADR numbering governance / `related_concerns` (van Heesch C1–C23) | Governance overhead for a repo you maintain, not one you're narrating. |
| `maps_to` resolving against `boundary.yaml` | No `boundary.yaml` exists for a foreign repo. |

## 5. `maps_to` in this model

Instead of anchoring to a `boundary.yaml`, `maps_to` (when included in the
body's "Maps to" section, or as an optional top-level field if the consuming
code wants it structured) references a **context id from
`<target>/.odyssey/inventory.yaml`** — the district the decision most directly
affects. Records inherit `provenance: inferred` from the inventory context
they map to; there is no separate provenance field on the record itself.

## 6. Workflow — retro-extraction from a merged PR

1. Read the PR's diff (`extract_diffs.py` output) and touched files.
2. Identify zero or more *structural* decisions in the diff (see §3.3).
3. For each: fill the shape in §1, using `references/adr-template.md` as the
   body skeleton. Ground `problem`/`decision`/`alternatives`/`forces` in what
   the diff and surrounding code actually show — never speculate beyond the
   evidence.
4. Assign the next free `ADR-NNNN` id.
5. Write/merge into `<target>/.odyssey/data/adrs.json`, regenerate
   `data/adrs.js`, and set this PR's `adrs: ["ADR-NNNN", ...]` array in
   `data/story.json` so story mode's level 3 can pull `alternatives`/`forces`
   straight from these records (see `story-mode.md` §2).
