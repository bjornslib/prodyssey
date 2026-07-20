---
title: "Stack Card — Python / FastAPI"
status: active
type: reference
last_verified: 2026-07-16
grade: authoritative
---

# Stack: python-fastapi — FastAPI backend (async Python API)

## Detect

- `pyproject.toml` or `requirements*.txt` declares `fastapi`
- `FastAPI(` instantiated in an entrypoint (`main.py`, `app.py`, or `app/` package)
- Usually accompanied by `uvicorn` (or `gunicorn` with uvicorn workers)

Python codebase without `fastapi` → fall through to `generic.md`.

## Reference Structure

```
app/
├── api/ or routers/    # HTTP layer only: routing, status codes, dependency wiring
├── services/           # business logic; no HTTP or ORM session concerns
├── models/             # ORM entities (SQLAlchemy/SQLModel)
├── schemas/            # Pydantic request/response models — separate from ORM
├── core/config.py      # settings via pydantic-settings; single source of env config
└── db/session.py       # engine/session lifecycle
tests/
alembic/ or migrations/ # schema migrations under version control
```

Rationale for the boundaries:
- **schemas/ vs models/** — Pydantic wire contracts and ORM persistence models change for
  different reasons; conflating them leaks storage shape into the public API and blocks
  independent evolution.
- **routers/ vs services/** — keeps business logic testable without an HTTP client and
  keeps handlers thin enough to audit for auth/validation at a glance.
- **core/config.py** — one place where environment crosses into code (12-factor config).

## Boundary Rules

Each rule is grep-checkable; report violations as architecture findings.

1. Routers never import ORM models directly — they call services.
   Check: `grep -rn "from app.models\|from ..models" app/api/ app/routers/`
2. Schemas never import from models (no ORM leakage into wire contracts).
   Check: `grep -rn "models" app/schemas/`
3. Services never import from routers (dependency points inward).
   Check: `grep -rn "from app.api\|from app.routers" app/services/`
4. `os.environ` / `os.getenv` only in `core/config.py`.
   Check: `grep -rn "os.environ\|os.getenv" app/ --include="*.py" | grep -v core/config`

## Corpus Load

- `corpus/principles/python/004_clean_architecture.yaml`
- `corpus/principles/python/007_type_hints_static_analysis.yaml`
- `corpus/principles/python/012_async_await.yaml`
- `corpus/principles/python/014_dependency_management.yaml`
- `corpus/principles/architecture/003_hexagonal_architecture.yaml`
- `corpus/principles/security/api_security.yaml`
- `corpus/principles/security/tenant_isolation.yaml`
- `corpus/principles/security/layer_boundaries.yaml`

Review mode already loads all of `corpus/principles/security/*`; the security entries
here exist so design mode gets them too. Load further `corpus/principles/python/*`
craft cards on demand via `corpus-index.md` symptom lookup.

## Review Checks

Stack-specific smells beyond the generic corpus:

- **Sync-in-async**: blocking calls (`requests`, `time.sleep`, sync DB drivers) inside
  `async def` handlers — stalls the event loop.
- **Schema/ORM conflation**: ORM models returned directly from endpoints, or a single
  class serving as both Pydantic schema and table definition without a deliberate ADR.
- **Missing auth dependency**: routers registered without an auth `Depends(...)` on
  non-public endpoints.
- **Migration drift**: models changed with no matching Alembic revision.
- **Config sprawl**: settings read outside `core/config.py` (see boundary rule 4).

## ADR Topics

Decisions this stack forces — during retro-extraction, check each has a record:

- Sync vs async stack (drivers, ORM session strategy)
- ORM choice and session/unit-of-work pattern (SQLAlchemy vs SQLModel vs none)
- Migration strategy (Alembic autogenerate discipline, rollout ordering)
- Background work (BackgroundTasks vs Celery/ARQ vs external queue)
- AuthN/AuthZ approach (JWT vs session, where tenancy is enforced)
