# Backend Architecture Baseline

Taskiller is a **modular monolith** with a client-independent REST API. The web app is not privileged; web, Android, iOS, desktop and future clients use the same API.

## Chosen stack

- Python 3.14
- Django 5.2 LTS / Django REST Framework
- Pydantic v2 / pydantic-settings
- Django ORM
- psycopg 3
- Django migrations
- PostgreSQL (Neon in production; PostgreSQL 18 locally/CI)
- pytest + pytest-asyncio
- Ruff
- Pyright
- uv
- Docker/OCI
- GitHub Actions
- Render Free for Django ASGI and the embedded worker; Vercel hosts the web client
- Mailjet HTTPS authentication mail; external five-minute uptime checks

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
- Django models do not double as public API schemas.
- Domain modules own their repositories/tables.
- UTC is stored server-side; user timezone is an IANA string.
- No Redis or microservices are introduced for v1 correctness.
- Active timers are state/timestamps in PostgreSQL, never in-memory countdowns.
- Idempotency and optimistic concurrency are required for cross-device mutations.

## v1 release architecture

All eight planned backend rounds are implemented. The modular-monolith boundary remains unchanged: PostgreSQL is the sole durable source of truth, Focus recommendations are deterministic/versioned, Execution uses append-only Events plus aggregate state, Analytics derives from immutable historical snapshots, and Operations provides privacy lifecycle, rate limiting and the PostgreSQL outbox.

The API and outbox worker share one Render Free service and image. External five-minute uptime checks keep it awake. The launcher supervises both processes. Django migrations run under a transaction-scoped advisory lock, and readiness checks database connectivity and pending migrations. No paid worker, broker, or cache is required.

Queue processing uses unique claim fences, periodic lease recovery, and atomic effects/acknowledgement. Exports use repeatable-read snapshots; authentication mail jobs store references and reconstruct tokens with a server-side HMAC. Current migrations establish database uniqueness, ownership/hierarchy, and immutable-history rules independently of the archived FastAPI implementation.

Cross-cutting controls include request IDs, sanitized JSON logging, browser-origin enforcement, trusted-host/CORS configuration, authentication budgets, security headers, Problem codes, and contract/database-invariant regression tests. The original framework transition occurred before real users; current validation is recorded in root `VALIDATION.md`.
