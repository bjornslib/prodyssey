---
title: "Stack Card — Generic Fallback"
status: active
type: reference
last_verified: 2026-07-16
grade: authoritative
---

# Stack: generic — fallback when no card matches

Applies when no other card's `## Detect` markers match. Also covers language matches
without a framework card — e.g. a plain-Python service that isn't FastAPI.

## Detect

Always matches, last in precedence order.

## Reference Structure

No canonical layout is imposed. Use the layering defaults from
`corpus/principles/architecture/003_hexagonal_architecture.yaml` (ports & adapters) and
`corpus/principles/architecture/007_architectural_boundaries.yaml` as the diff target:
a core of domain/business logic that does not import I/O, frameworks, or storage, with
adapters at the edges.

## Boundary Rules

1. The dependency rule: inner layers (domain, business logic) never import outer layers
   (HTTP, UI, DB drivers, framework code). Identify the codebase's inner packages, then
   grep them for framework/driver imports.
2. Configuration crosses into code in one place, not scattered env reads.

## Corpus Load

1. Identify the primary language from manifests (`pyproject.toml` / `package.json` /
   `go.mod` / ...).
2. If a matching language corpus exists, load its core cards:
   - Python → `corpus/principles/python/*` (start with `001_deep_modules`,
     `004_clean_architecture`, `007_type_hints_static_analysis`)
   - TypeScript/React → `corpus/principles/react_typescript/*` (start with `001`, `002`)
3. Otherwise, root corpus only — `corpus/principles/architecture/*` plus
   `corpus-index.md` symptom lookup.

## Review Checks

None beyond the generic corpus — that is what the corpus chain already covers.

## ADR Topics

- Persistence choice and how storage is abstracted from the domain
- Module/boundary strategy (monolith layering, package structure, service split)
- External integration style (sync calls vs events; where anti-corruption sits)
