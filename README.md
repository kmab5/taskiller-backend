# taskiller-backend

Client-independent backend for **Taskiller** — a task execution and focus system built around Projects, Sprints, Chores, Focus Plans, Execution Sessions, analytics, and evidence-informed recommendations.

## Status

**Round 4 complete: Focus & Recommendation Engine.**

Implemented so far:

- FastAPI application/configuration foundation
- async SQLAlchemy + psycopg/PostgreSQL integration
- Alembic migrations
- Docker/CI/health probes/OpenAPI export
- users and versioned profile/preferences
- Argon2id password hashing
- short-lived JWT access credentials
- opaque, HMAC-hashed, rotating refresh credentials
- database-backed device sessions with immediate revocation
- refresh-token replay detection and session-family revocation
- email-verification and password-reset one-time token primitives
- session listing/revocation and logout-all
- RFC-style structured API errors
- ETag/If-Match optimistic concurrency for user-owned mutable resources
- built-in and custom Work Types with work-characteristic profiles
- Project/Sprint/Chore CRUD with bounded hierarchy rules
- PostgreSQL-backed hierarchy enforcement
- WorkItem state machine, ordering, soft deletion, trees and next-action selection
- database-backed idempotency for create/reorder mutations
- cursor pagination and ownership-safe Work queries
- immutable, versioned Focus Plan recommendation snapshots
- deterministic evidence-informed Focus recommendation engine
- preference-aware strategy selection without fake confidence scores
- Chore and Sprint recommendation generation
- study/retrieval-aware plans
- editable Focus Plans with normalized ordered segments
- reusable generic Focus Plan templates
- Focus Plan ETags, soft deletion, pagination and idempotent creates

Round 5 will add the Execution Session and append-only event engine.

See:

- `docs/ARCHITECTURE.md`
- `docs/AUTH.md`
- `docs/ROUND_2.md`
- `docs/ROUND_3.md`
- `docs/ROUND_4.md`
- `docs/FOCUS.md`
- `docs/WORK.md`
- `docs/DEVELOPMENT_ROUNDS.md`
- `openapi/current.json` — OpenAPI generated from the implemented application
- `openapi/planned-v1.yaml` — full v1 planning baseline

## Stack

Python 3.14 · FastAPI · Pydantic v2 · SQLAlchemy 2 · psycopg 3 · Alembic · PostgreSQL · PyJWT · pwdlib/Argon2id · pytest · Ruff · Pyright · uv · Docker

Production direction: **Koyeb API + Neon PostgreSQL**.

## Local setup

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --dev
uv run alembic upgrade head
uv run uvicorn taskiller.main:app --app-dir src --reload
```

Then open:

- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`
- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`

## Quality commands

```bash
make lint
make typecheck
make test
make test-integration
make openapi
```

`make test-integration` requires `TASKILLER_TEST_DATABASE_URL` and a database migrated to `head`. CI provisions PostgreSQL and runs the migration before the full test suite.

## Environment model

- `local`
- `test`
- `staging`
- `production`

Staging and production use independent databases and secrets. The app refuses the development auth secrets in staging/production.
