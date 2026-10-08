# Production Deployment — Django Cutover

Taskiller production is now:

```text
Vercel / SvelteKit
       |
       | HTTPS /api/v1
       v
Render Free / Django ASGI
       | \
       |  \ HTTPS
       |   -> Mailjet
       |
       +---- Neon PostgreSQL
       |
       +---- embedded Django outbox worker
```

## One-time schema adoption

Before the first Django production deployment:

```bash
uv lock
uv sync --dev
python apply_django_phase8.py
PYTHONPATH=src uv run python scripts/prepare_django_baseline.py
```

Review and commit the generated `django_domain/migrations/0001_...py`.

The live Neon database must already be at legacy Alembic head `20260930_0007`.

On the first Django startup, `scripts/django_cutover_migrate.py` runs
`migrate --fake-initial`: Django creates its built-in admin/auth/session tables and records the
existing Taskiller domain schema as its initial migration without recreating those tables.

After this adoption, all new Taskiller schema changes must be Django migrations.

## Render

Docker starts:

```text
python scripts/run_django_production.py
```

This:

1. applies committed Django migrations;
2. starts the Django outbox worker when `TASKILLER_EMBEDDED_WORKER_ENABLED=true`;
3. starts Django ASGI with Uvicorn.

Required new secret:

```text
TASKILLER_DJANGO_SECRET_KEY=<strong independent secret>
```

Existing JWT, token-HMAC, Mailjet, database, CORS and refresh-cookie environment variables remain.

## OpenAPI

`/openapi.json` serves the fully typed committed `openapi/current.json`.

The Django runtime is audited against that contract in CI. This intentionally avoids replacing
the client contract with the less-detailed transitional drf-spectacular schemas.

## Rollback

Until Django has been stable in production, the previous FastAPI entrypoint remains in the codebase:

```bash
PYTHONPATH=src uv run uvicorn taskiller.main:app --host 0.0.0.0 --port 8000
```

Do not create new Alembic migrations after Django adoption.
