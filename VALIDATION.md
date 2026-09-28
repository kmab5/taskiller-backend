# Round 2 Validation

Validated on 2026-09-28 in the artifact environment.

## Passed locally

- `pytest -m "not integration"`: **15 passed**
- full `pytest`: **15 passed, 8 skipped**
  - the eight skipped tests require `TASKILLER_TEST_DATABASE_URL`
- `python -m compileall src tests alembic`: passed
- import walk across the `taskiller` package: passed
- SQLAlchemy `configure_mappers()`: passed, **6 mapped tables**
- generated FastAPI OpenAPI document: passed, written to `openapi/current.json`
- Alembic offline `upgrade head --sql`: passed
- Alembic offline downgrade `20260928_0001:base --sql`: passed
- source/test/migration 100-character line-length scan: passed

## PostgreSQL integration coverage included

CI provisions PostgreSQL 18, applies Alembic migrations, and then runs the complete test suite. The Round 2 integration suite covers:

- registration and refresh-cookie issuance
- profile ETag/If-Match behavior
- email verification
- refresh rotation and old-token replay revocation
- password reset, password replacement and session revocation
- per-device session listing/revocation
- preferences optimistic concurrency
- proof that plaintext refresh credentials are not persisted
- non-disclosing password-reset requests for unknown email addresses
- readiness against PostgreSQL

## Environment limitations

This artifact runtime has Python 3.13 rather than the project target Python 3.14 and has no PostgreSQL server/psycopg installation. Network access is disabled, so the missing project dependencies, Ruff and Pyright could not be installed here. The source includes a local Argon2 fallback solely so dependency-independent unit tests can execute; normal project installation uses `pwdlib[argon2]` as declared in `pyproject.toml`.

Accordingly, PostgreSQL integration, Ruff and Pyright are **not claimed as locally executed**. `.github/workflows/ci.yml` runs Python 3.14, installs the declared dependencies, runs Ruff/Pyright, migrates PostgreSQL, runs the full suite, exports OpenAPI and builds the container.
