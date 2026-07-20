---
title: "Stack Card — Next.js"
status: draft
type: reference
last_verified: 2026-07-16
grade: draft
---

# Stack: nextjs — Next.js (React meta-framework)

> STUB — detection and inheritance are authoritative; the remaining sections are a
> reasoning sketch awaiting a real Next.js engagement to flesh out.

## Detect

- `package.json` declares `next`, or `next.config.{js,mjs,ts}` present
- Takes precedence over `react-typescript.md` (most-specific card wins)

## Inherits

`react-typescript.md` — load that card first; the rules below are Next.js additions.

## Boundary Rules (sketch)

1. Server/client component discipline: `'use client'` only where interactivity requires
   it; no server-only imports (DB clients, secrets, `fs`) in client components.
2. Route handlers (`app/**/route.ts`) stay thin — delegate to services, mirroring the
   routers-vs-services rule in `python-fastapi.md`.
3. Data fetching belongs in server components or route handlers, not client-side
   effects, unless the data is user-interactive by nature.

## ADR Topics (sketch)

- Rendering strategy per route (SSR / SSG / ISR / client)
- App Router vs Pages Router (and migration state if mixed)
- Where the API layer lives (route handlers vs separate backend)
- Caching and revalidation policy
