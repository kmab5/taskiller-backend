# Round 3 Validation

Validated on 2026-09-28 in the artifact environment.

## Reported CI lint fixes

The Round 2 Ruff failures supplied before this round were corrected before Work-domain implementation:

- import organization in `alembic/env.py`, `auth/routes.py` and `users/schemas.py`
- unnecessary quoted annotations in settings, ORM models and user schemas
- `JsonFormatter._reserved` marked as `ClassVar[set[str]]`

New Round 3 source follows the same 100-character Ruff configuration. Ruff itself is not installed in this offline artifact runtime, so a successful local Ruff execution is not claimed; CI remains authoritative for Ruff and Pyright.

## Passed locally

- `pytest tests/unit -q`: **26 passed**
- full `pytest -q`: **26 passed, 14 skipped**
  - the fourteen skipped tests require `TASKILLER_TEST_DATABASE_URL`
- `python -m compileall src tests alembic scripts`: passed
- SQLAlchemy `configure_mappers()`: passed, **9 mapped tables**
- FastAPI application/OpenAPI construction: passed
- generated OpenAPI 3.1 document: **23 paths / 31 operations**
- OpenAPI export written to `openapi/current.json`
- Alembic offline `upgrade head --sql`: passed, including Round 3 tables, seeds and hierarchy trigger
- Alembic offline downgrade `20260928_0002:base --sql`: passed
- source/test/migration 100-character line-length scan: passed

## PostgreSQL coverage included

CI provisions PostgreSQL 18, upgrades to Alembic `head`, and executes the integration suite. Round 3 adds coverage for:

- built-in WorkType visibility
- custom WorkType idempotent creation, update and deletion
- immutable system WorkTypes
- Project -> Sprint -> Chore and Project -> Chore hierarchy rules
- direct database rejection of an invalid orphan Sprint, proving trigger enforcement
- tree traversal and Project next-action selection
- terminal Project next-action behavior
- WorkItem state transitions and completion timestamp handling
- soft deletion and parent deletion guards
- sibling reordering and idempotent replay
- idempotency-key request mismatch rejection
- stable cursor pagination
- `ON DELETE SET NULL` when a custom WorkType is removed

The existing Round 2 authentication/readiness integration tests remain in the suite and were adjusted so cleanup does not erase globally seeded WorkTypes.

## Environment limitations

This artifact runtime has Python 3.13 rather than the project target Python 3.14 and does not contain PostgreSQL, psycopg, Ruff or Pyright. Network access is disabled, so those missing tools cannot be installed here.

Accordingly, the PostgreSQL integration tests, Ruff and Pyright are **not claimed as locally executed**. `.github/workflows/ci.yml` uses Python 3.14, installs the declared dependencies, runs Ruff and Pyright, provisions PostgreSQL 18, applies migrations, runs the complete suite, exports OpenAPI and builds the container.
