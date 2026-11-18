# Repository Guidelines

## Related Repositories & Agent Context

Read [.agents/project-context.md](.agents/project-context.md) for the repository map, shared domain, contract workflow, and integration checks verified on 2026-11-18.

- `D:/Code/taskiller`: product specifications, research, examples, and brand assets. Its original Node/NestJS stack and offline-write proposal are historical; consult active implementations for current behavior.
- `D:/Code/taskiller-web`: SvelteKit/Svelte 5 client. Read its `AGENTS.md` before editing there. Coordinate API changes with its OpenAPI snapshot, generated types, and Django browser tests.

## Project Structure & Module Organization

Active Python code lives in `src/taskiller/`. `django_project/` contains settings and ASGI routing; `django_api/` contains DRF views and services; `django_domain/` owns ORM models and migrations; `django_operations/` implements the outbox worker. Feature packages such as `focus/` and `analytics/` hold supporting logic and schemas.

Tests live in `tests/unit/django/`. Operational checks live in `scripts/`, architecture and runbooks in `docs/`, and deployment configuration in `deploy/` and root Docker/Render files. `openapi/current.json` is the canonical client contract. Treat `legacy_backend/` as historical reference only.

## Build, Test, and Development Commands

Use Python 3.14 and `uv`:

- `uv sync --dev`: install runtime and development dependencies.
- `docker compose up -d postgres`: start local PostgreSQL.
- `uv run python manage.py migrate`: apply Django migrations.
- `uv run python manage.py runserver 0.0.0.0:8000`: start the API.
- `uv run python manage.py taskiller_worker`: run the background worker.
- `uv run pytest`: run tests.
- `uv run ruff check .` and `uv run ruff format --check .`: validate style.
- `uv run pyright`: check the explicitly configured subset of modules.
- `make check`: run compilation, style, typing, tests, and release audits.
- `docker build -t taskiller-backend:local .`: build the production image.

Set `PYTHONPATH=src` for management commands and audit scripts; in PowerShell, use `$env:PYTHONPATH = "src"`.

## Coding Style & Naming Conventions

Use four-space indentation, double quotes, and a 100-character line limit. Ruff handles formatting, linting, and import ordering. Use `snake_case` for modules/functions and `PascalCase` for classes. Follow the existing view/service separation. Use Django migrations for schema changes; do not add Alembic migrations.

## Testing Guidelines

Use pytest and pytest-asyncio; name files `test_*.py` and functions `test_*`. Add regression coverage for changed behavior. Mark PostgreSQL-dependent tests `integration`. CI runs `uv run pytest --cov=taskiller --cov-report=term-missing --cov-report=xml`; no numeric coverage threshold is configured. Validate migration drift and API contract compatibility when relevant.

Database regressions live in `tests/integration/`. Set `TASKILLER_ENV=test` and matching `TASKILLER_DATABASE_URL`/`TASKILLER_TEST_DATABASE_URL` to a disposable local database; integration tests skip without an explicit test URL.

## Commit & Pull Request Guidelines

Recent commits use short prefixes such as `fix:` and `fix/cg:`. Keep messages concise and specific. PRs should describe behavior changes, link relevant issues, report validation commands, and explain migration or API-contract impact. Ensure CI passes.

## Security & Configuration

Copy `.env.example` to `.env` for local configuration. Keep secrets and database credentials out of commits. Consult `docs/SECURITY.md` and deployment runbooks before changing authentication or production settings.

Keep deployment entirely no-cost: Render Free with the embedded worker, Neon, Mailjet, and Vercel. External five-minute uptime checks are already configured by the owner. Django replaced FastAPI before real users existed; use the current Django schema and migrations.
