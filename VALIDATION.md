# Backend v1 / Round 8 Validation

Validated on 2026-09-28 from the GitHub Round-7 source tree.

## Source provenance

Canonical repository: `kmab5/taskiller-backend`.

Round 8 began from GitHub `main` commit:

```text
751cd9108a94c7edd516a3c659e3469abc4cb64e
feat/cg: round-7, privacy and operations
```

Its Git tree was `385a5727d8b6dfa7c541979509ed9571f53c0081`. Before Round-8 edits, the local working tree used for implementation produced the same tree SHA, so the implementation baseline was byte-for-byte the current upstream contents.

## Passed locally

- full `pytest -q`: **68 passed, 31 skipped**
  - all 31 skips are tests requiring `TASKILLER_TEST_DATABASE_URL`
  - the skipped set includes the new v1 cross-domain PostgreSQL release smoke test
- `python -m compileall -q src tests alembic scripts`: passed
- SQLAlchemy mapper configuration through the complete application: passed, **20 mapped tables**
- generated OpenAPI: **3.1.0**, API version **1.0.0**, **41 paths / 56 operations**
- `scripts/release_check.py`: passed
  - unique/non-missing operation IDs
  - protected-vs-public operation audit
  - complete literal `ApiError`/problem-code catalog
  - committed/generated OpenAPI equality
  - readiness/Alembic-head consistency
- Alembic offline `upgrade head --sql`: passed through `20260928_0006`
- Alembic offline full downgrade `20260928_0006:base --sql`: passed
- source/test/script/migration 100-character line-length scan: passed
- AST unused-import sanity scan: passed
- `git diff --check`: passed

## Round 8 release coverage

Unit coverage includes deployed-configuration rejection, production SMTP requirements, SMTP sender selection, request-ID propagation, security headers/no-store behavior, sanitized unexpected-error responses, OpenAPI Problem/catalog construction, and Koyeb forwarded-client-address interpretation.

The new PostgreSQL release smoke test crosses the public v1 product path in one scenario:

1. registration;
2. Work Type lookup;
3. Project → Sprint → Chore creation;
4. Focus recommendation and selected Focus Plan creation;
5. Execution Session start and completion;
6. analytics verification;
7. data-export request;
8. outbox export processing;
9. signed export download and secret-exclusion verification.

CI additionally performs a real PostgreSQL migration upgrade → downgrade-to-base → upgrade round trip before the complete integration suite.

## Production safeguards verified structurally

- startup migrations use a PostgreSQL session advisory lock;
- readiness verifies both database connectivity and exact Alembic revision;
- the API and outbox worker can share the same image while running as separate processes;
- an embedded worker remains available only as a one-service preview/development topology;
- production configuration rejects development secrets, wildcard hosts/CORS, local database URLs, and non-SMTP authentication email delivery;
- generated v1 OpenAPI documents the canonical Problem response and complete stable error-code set.

## Environment limitations

This artifact runtime uses Python 3.13 while the repository targets Python 3.14. PostgreSQL, Ruff, Pyright, and Docker are not installed in this runtime, and direct package/network installation is unavailable.

Therefore the following are **not claimed as locally executed**:

- the 31 PostgreSQL integration tests;
- Ruff lint and Ruff format check;
- strict Pyright;
- OCI/Docker image build and runtime health check.

The repository CI remains authoritative for those checks. `.github/workflows/ci.yml` is configured for Python 3.14, Ruff, strict Pyright, PostgreSQL 18, migration round-trip, complete tests, release-contract verification, committed OpenAPI verification, and container build/import validation.
