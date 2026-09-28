# Round 5 Validation

Validated on 2026-09-28 in the artifact environment.

## Passed locally

- full `pytest -q`: **49 passed, 24 skipped**
  - the 24 skipped tests require `TASKILLER_TEST_DATABASE_URL`
  - six of those are Round 5 PostgreSQL execution tests
- `python -m compileall src tests alembic scripts`: passed
- SQLAlchemy mapper configuration: passed, **15 mapped tables**
- FastAPI application/OpenAPI construction: passed
- generated OpenAPI: **3.1.0**, API version **0.5.0**, **32 paths / 46 operations**
- generated local OpenAPI `$ref` resolution: no broken references
- OpenAPI export written to `openapi/current.json`
- Alembic offline `upgrade head --sql`: passed through Round 5
- Alembic offline downgrade `20260928_0004:base --sql`: passed
- source/test/migration 100-character line-length scan: passed
- simple AST unused-import scan for Round 5 files: passed
- `git diff --check`: passed

## Round 5 regression coverage

Unit/contract coverage verifies stable Execution paths/operation IDs, required idempotency headers, Event `If-Match`, segment-index request shape, server-only `session_started`, structured WorkItem-completion payloads, and timezone-aware informational client timestamps.

PostgreSQL integration coverage is included for:

- start → pause → resume → advance → explicit WorkItem completion → finish → review;
- server-created initial `session_started`/`segment_started` history;
- one-open-Session enforcement;
- stale cross-device ETag rejection;
- abandonment releasing the open-Session slot;
- exact event idempotency returning the original post-event snapshot;
- conflict on idempotency-key reuse with different material;
- immutable Session Focus Plan snapshots after later plan edits;
- rejection of skipping a required segment;
- direct-SQL rejection of Session snapshot mutation by the database trigger.

Existing authentication, Work and Focus suites remain included.

## Database invariants added

The Round 5 migration adds a partial unique index for one open Session per user and trigger-level validation for Session ownership/references. Session identity and snapshots are immutable after creation, terminal states cannot be reopened, each aggregate mutation must increment `version` by exactly one, Session Event owners must match their parent Session, and Session Event rows reject updates.

## Environment limitations

This artifact runtime uses Python 3.13 while the project target is Python 3.14. PostgreSQL, psycopg, Ruff and Pyright binaries are not installed, and outbound network access from the container is disabled, so those missing tools cannot be installed here.

Therefore PostgreSQL integration tests, Ruff and Pyright are **not claimed as locally executed**. CI remains authoritative: `.github/workflows/ci.yml` uses Python 3.14, installs declared dependencies, runs Ruff/Pyright, provisions PostgreSQL 18, applies migrations, runs the complete suite, exports OpenAPI and builds the container.
