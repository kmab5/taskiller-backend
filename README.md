# taskiller-backend

Client-independent backend for **Taskiller** — a task execution and focus system built around Projects, Sprints, Chores, Focus Plans, Execution Sessions and evidence-informed recommendations.

## Status

**Round 1: backend foundation.** Product endpoints are intentionally not implemented yet. The current app provides infrastructure, health probes and a reproducible structure for the domain rounds that follow.

See:

- `docs/ARCHITECTURE.md`
- `docs/AUTH.md`
- `docs/DEVELOPMENT_ROUNDS.md`
- `openapi/planned-v1.yaml` — planned v1 API contract from the product planning package

## Stack

Python 3.14 · FastAPI · SQLAlchemy 2 · psycopg 3 · Alembic · PostgreSQL · Pydantic · pytest · Ruff · Pyright · uv · Docker

Production direction: **Koyeb API + Neon PostgreSQL**. Authentication is native to the FastAPI backend: Argon2id credentials, short-lived JWT access tokens and rotating opaque refresh sessions; see `docs/AUTH.md`.

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

## Environment model

- `local`
- `test`
- `staging`
- `production`

Staging and production will use separate databases and secrets. Auth token keys, lifetimes and client origins are environment-configured.
