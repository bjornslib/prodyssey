---
# --- decision record (lite schema: references/decision-records-lite.md §1) ---
id: ADR-NNNN
title: "<decision name>"
state: approved          # retro-extractions from a merged PR are always "approved"
source_pr: NN
problem: "<the problem this decision answers>"
decision: "<the chosen option, one sentence>"
alternatives:             # >=1 entry — what was traded away
  - option: "<rejected option>"
    rejected_because: "<why>"
forces:                   # constraints/drivers: requirements, expertise, business
  - "<force>"
delivers:                 # MANDATORY value facet
  capability: "<what is now possible that was not before>"
  benefit: "<the value created and why it matters>"
  beneficiary: []          # e.g. operator | developer | the-business
---

# ADR-NNNN — <decision name>

## Context

<What situation demanded a decision. Facts, not advocacy. Note that this is a
retroactive extraction from a merged PR, not a design-time record.>

## Options considered

1. **<option A>.** <analysis; why rejected/accepted>
2. **<option B (chosen)>.** <analysis>

## Decision

<The chosen option and its scope. What is explicitly out of scope.>

## Consequences

- **Positive:** <...>
- **Constraint introduced:** <the invariant this decision establishes>
- **Negative / accepted:** <...>

## Value delivered

- **New capability:** <mirror delivers.capability>
- **Benefit:** <mirror delivers.benefit — why it is worth it>
- **Beneficiary:** <who gains>

## Maps to

District `<context-id>` from `.odyssey/inventory.yaml`.
