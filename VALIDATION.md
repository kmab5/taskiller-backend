# Round 4 Validation

Validated on 2026-09-28 in the artifact environment.

## Reported CI lint fixes

The four Ruff failures supplied for the Round 3 artifact were corrected before Round 4 implementation:

- `I001` in `src/taskiller/auth/routes.py`: removed the aliased FastAPI `Path` import and normalized the import block.
- `I001` in `src/taskiller/db/models.py`: placed the all-caps `JSON` import in Ruff/isort type order and normalized the SQLAlchemy import block.
- `I001` in `src/taskiller/work/routes.py`: removed `Path`/`status` aliases and normalized the FastAPI import block.
- `SIM117` in `tests/integration/work/test_work_flow.py`: combined the nested context managers into one `with` statement.

Round 4 source was also checked for 100-character line length, unused top-level imports, quoted forward annotations, mutable unannotated class literals, and nested single-body `with` statements. Ruff and Pyright binaries are not installed in this offline artifact runtime, so a successful local execution of those tools is not claimed; CI remains authoritative for the complete Ruff/Pyright rule set.

## Passed locally

- full `pytest -q`: **41 passed, 18 skipped**
  - the eighteen skipped tests require `TASKILLER_TEST_DATABASE_URL`
- `python -m compileall src tests alembic scripts`: passed
- SQLAlchemy `configure_mappers()`: passed, **12 mapped tables**
- FastAPI application/OpenAPI construction: passed
- generated OpenAPI 3.1 document: **27 paths / 38 operations**, API version **0.4.0**
- all generated local OpenAPI `$ref` targets resolve
- OpenAPI export written to `openapi/current.json`
- Alembic offline `upgrade head --sql`: passed through Round 4
- Alembic offline downgrade `20260928_0003:base --sql`: passed
- `git diff --check`: passed
- source/test/migration 100-character line-length scan: passed

## Round 4 regression coverage

The unit/contract suite verifies:

- stable Focus API paths and operation IDs
- required idempotency headers on recommendation/plan creation
- Focus segment duration/link validation
- template/recommendation source invariants
- short high-continuity tasks remain a single block
- long structured work includes flexible recovery without assuming 25/5 Pomodoro
- learning recommendations include retrieval/review when the resolved strategy allows it
- explicit continuous strategy remains continuous for learning work
- available-time budgets include suggested recovery breaks
- uncapped study plans preserve estimated active-work time
- generated work blocks remain at or below 90 minutes even with longer user block preferences

PostgreSQL integration coverage is included for recommendation idempotency, immutable recommendation snapshots, saving edited recommendation-derived plans, Focus Plan ETag updates/deletion, study recommendations, and Project recommendation rejection. Existing authentication, readiness, Work hierarchy/state/order/idempotency tests remain in the suite.

## Environment limitations

This artifact runtime has Python 3.13 rather than the project target Python 3.14 and does not contain PostgreSQL, psycopg, Ruff or Pyright. Network access from the execution container is disabled, so those missing tools cannot be installed here.

Accordingly, PostgreSQL integration tests, Ruff and Pyright are **not claimed as locally executed**. `.github/workflows/ci.yml` uses Python 3.14, installs the declared dependencies, runs Ruff and Pyright, provisions PostgreSQL 18, applies migrations, runs the complete suite, exports OpenAPI and builds the container.
