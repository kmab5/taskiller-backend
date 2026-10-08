# Django Migration — Phase 2 Schema Bridge

Prepared from:

- backend `main`: `b1de8835a1eb348a7389378297187e76c9715c51`
- frontend `main`: `c49bedaf7dc33dc13403d298be092b02562def09`

This package is cumulative because the latest backend branch does not yet contain the Phase 1 files.

## Phase 2 outcome

Django now has read mappings for all 20 existing Taskiller tables:

- users / preferences / auth sessions
- credential token tables
- idempotency
- Work Types and Work Items
- Focus recommendations / plans / segments
- Execution sessions / events / reviews
- exports / deletion requests / outbox
- rate limits / security events

Every Taskiller domain model uses:

```python
class Meta:
    managed = False
```

and a database router rejects Django migrations for the bridge app.

SQLAlchemy/Alembic remain the sole schema owner.

## Composite primary keys

Django 5.2 `CompositePrimaryKey` maps:

```text
idempotency_records(owner_id, scope, idempotency_key)
rate_limit_buckets(scope, subject_hash)
```

These models are deliberately excluded from Django Admin because Django 5.2 does not support
CompositePrimaryKey models in the admin.

## Read-only Admin

The following operational objects are visible in Django Admin:

- Taskiller users
- preferences
- auth sessions
- Work Types
- Work Items
- Focus recommendations
- Focus Plans / segments
- Execution Sessions / Events / Reviews
- data exports
- account deletion requests
- outbox jobs
- security events

All Taskiller-backed admins disable add/change/delete.

Credential hashes/tokens and composite-key internals are intentionally not registered.

## Parity checks

`django_phase2_schema_parity.py` verifies for all 20 tables:

- table exists
- Django model remains unmanaged
- exact column set matches PostgreSQL
- primary-key columns match PostgreSQL

`django_phase2_row_parity.py` then proves Django ORM and SQLAlchemy see:

- the same row count
- the same first row, field-for-field

for all 20 mapped tables.

## Schema ownership

Do **not** turn these models into `managed=True` yet.

Do **not** generate Taskiller domain DDL from Django yet.

Django built-in admin/auth tables may be created later in an isolated step, but Phase 2 CI does not
need them. The production Render command remains FastAPI.

## Validation sequence

```bash
uv lock
uv sync --dev

PYTHONPATH=src uv run python manage.py check

uv run ruff format .
uv run ruff check .
uv run pyright

uv run alembic upgrade head

PYTHONPATH=src uv run python scripts/django_phase2_schema_parity.py
PYTHONPATH=src uv run python scripts/django_phase2_row_parity.py
PYTHONPATH=src uv run python scripts/django_phase2_smoke.py

uv run pytest
PYTHONPATH=src uv run python scripts/release_check.py

docker build -t taskiller-backend:django-phase2 .
```

## Phase 3 entry criteria

Only move to API/auth migration after:

1. all 20 schema mappings pass parity;
2. row parity passes on a database containing representative data;
3. existing FastAPI tests remain green;
4. frontend requires no changes;
5. no Django-generated DDL touches existing Taskiller tables.

## Phase 4

The Work domain is implemented in Django/DRF. See `docs/DJANGO_PHASE4.md`.

## Phase 6

The Execution domain is implemented in Django/DRF. See `docs/DJANGO_PHASE6.md`.

## Phase 7

Analytics and the outbox/retention worker are migrated. See `docs/DJANGO_PHASE7.md`.
