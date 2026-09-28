# Backend Architecture Baseline

Taskiller is a **modular monolith** with a client-independent REST API. The web app is not privileged; web, Android, iOS, desktop and future clients use the same API.

## Chosen stack

- Python 3.14
- FastAPI
- Pydantic v2 / pydantic-settings
- SQLAlchemy 2 async ORM/Core
- psycopg 3
- Alembic
- PostgreSQL (Neon in production; PostgreSQL 18 locally/CI)
- pytest + pytest-asyncio
- Ruff
- Pyright
- uv
- Docker/OCI
- GitHub Actions
- Koyeb for the API

## Domain modules

```text
Identity/Auth
     |
     v
Work <---- Focus
  ^         ^
  |         |
  +---- Execution ----> Analytics
             |
             +--------> Operations/outbox
```

The Python application owns both Taskiller identity/session state and domain state. Authentication remains a dedicated module with narrow interfaces so future OAuth/passkey providers can be added without leaking provider concerns into Work, Focus, Execution or Analytics.

## Rules

- Business logic stays outside HTTP route functions.
- SQLAlchemy models do not double as public API schemas.
- Domain modules own their repositories/tables.
- UTC is stored server-side; user timezone is an IANA string.
- No Redis or microservices are introduced for v1 correctness.
- Active timers are state/timestamps in PostgreSQL, never in-memory countdowns.
- Idempotency and optimistic concurrency are required for cross-device mutations.

## Implemented through Round 3

Identity/Auth and Work are production-shaped modules. Work owns WorkTypes and WorkItems; the shared core currently provides configuration, structured problems and mutation idempotency. PostgreSQL is the source of truth for ownership, hierarchy, ordering and version state.

Round 4 adds Focus and Recommendations without changing the Work API's containment semantics.
