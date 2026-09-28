# Round 8 — Hardening & Production Release

Round 8 closes the planned v1 backend scope and moves the service from feature-complete to release-shaped.

## Production hardening added

- API version promoted to **1.0.0**.
- Every response receives an `X-Request-ID`; a valid incoming ID is propagated.
- Structured request logs contain request ID, method, path, status, duration and normalized client IP.
- API responses get `no-store`; security headers add nosniff, frame denial, no-referrer and a restrictive permissions policy. Production also emits HSTS.
- Unhandled exceptions are logged server-side and returned as sanitized `application/problem+json` without exception details.
- Trusted-host and deployed CORS validation prevent wildcard production configurations.
- Koyeb `x-forwarded-for` handling uses the final address because Koyeb documents that final entry as the address it can certify.
- Database client pooling is bounded/configurable for Neon/PostgreSQL.
- `/health/ready` verifies both PostgreSQL connectivity and the expected Alembic revision. Schema drift is not considered ready.
- `/health/version` exposes application/release metadata without secrets.

## Deployment safety

`scripts/migrate.py` wraps Alembic upgrade in a PostgreSQL session advisory lock. The production container applies migrations before Uvicorn starts, preventing two new deploy instances from running the migration body concurrently.

The outbox worker can run either:

1. as a separate service using `python -m taskiller.operations.worker` (recommended production topology), or
2. embedded into the API with `TASKILLER_EMBEDDED_WORKER_ENABLED=true` for a one-service hobby/free deployment.

Embedded processing preserves the same PostgreSQL leasing/idempotency rules; it is a deployment convenience, not a separate execution model.

## Contract audit

The generated OpenAPI now includes a canonical `Problem` schema, a default `application/problem+json` response for every `/api/v1` operation, and the complete `x-taskiller-problem-codes` catalog. `scripts/release_check.py` fails CI if:

- an operation ID is missing/duplicated;
- a non-public v1 operation loses Bearer authentication;
- a literal `ApiError` code is missing from the catalog;
- the committed OpenAPI artifact differs from the running application.

## Release verification

CI now performs compile, Ruff lint/format, strict Pyright, full migration upgrade→base→upgrade roundtrip, complete PostgreSQL tests, generated OpenAPI contract verification, OCI image build and import validation.

`tests/integration/test_release_smoke.py` additionally tests the complete v1 user path from registration through export generation.
