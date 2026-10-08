# Phase 9 — Post-cutover Stabilization

Phase 9 hardens the Django production cutover.

## Production-boundary audit

```bash
PYTHONPATH=src uv run python scripts/django_phase9_runtime_audit.py
```

The Django production packages must not directly import FastAPI, SQLAlchemy, Alembic,
`taskiller.main`, the SQLAlchemy database runtime, or the legacy worker.

## Migration adoption audit

After the Phase 8 initial Django migration has been generated, committed and adopted:

```bash
PYTHONPATH=src uv run python scripts/django_phase9_baseline_audit.py
```

This requires exactly one `django_domain/0001_*.py`, managed domain models, no pending migrations,
and the expected adopted tables.

## Admin bootstrap

Set these only for the bootstrap operation:

```text
TASKILLER_ADMIN_EMAIL=<admin email>
TASKILLER_ADMIN_PASSWORD=<strong temporary secret>
```

Run:

```bash
PYTHONPATH=src uv run python manage.py bootstrap_taskiller_admin
```

Then remove `TASKILLER_ADMIN_PASSWORD` from the environment.

## Production-shaped smoke

```bash
PYTHONPATH=src uv run python scripts/django_phase9_production_smoke.py
```

## Frontend real-Django E2E

Apply the included frontend patch, start a disposable Django API configured to allow the local
Playwright origin, then:

```bash
TASKILLER_DJANGO_API_URL=http://127.0.0.1:8000 npm run test:e2e:django
```

FastAPI/Alembic rollback code remains for this stabilization release only.
