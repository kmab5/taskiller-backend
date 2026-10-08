# Django Migration — Phase 3 Auth + User API

Prepared against:

- backend `main`: `b1de8835a1eb348a7389378297187e76c9715c51`
- frontend `main`: `c49bedaf7dc33dc13403d298be092b02562def09`

The package is cumulative because Phase 1/2 are not present on backend `main`.

## Scope migrated to Django/DRF

### Auth

- POST `/api/v1/auth/register`
- POST `/api/v1/auth/login`
- POST `/api/v1/auth/refresh`
- POST `/api/v1/auth/logout`
- POST `/api/v1/auth/logout-all`
- GET `/api/v1/auth/sessions`
- DELETE `/api/v1/auth/sessions/{sessionId}`
- POST `/api/v1/auth/email-verification/request`
- POST `/api/v1/auth/email-verification/confirm`
- POST `/api/v1/auth/password-reset/request`
- POST `/api/v1/auth/password-reset/confirm`

### User

- GET/PATCH/DELETE `/api/v1/me`
- GET/PATCH `/api/v1/me/preferences`
- POST `/api/v1/me/export-requests`
- GET `/api/v1/me/export-requests/{exportRequestId}`
- GET `/api/v1/exports/{exportRequestId}/download`

## Preserved semantics

- HS256 access JWTs
- JWT issuer/audience/claims
- rotating opaque refresh credentials
- reuse detection and family revocation
- HttpOnly refresh cookie path/domain/SameSite/Secure behavior
- Argon2 password hashing
- device sessions
- Mailjet verification/reset delivery
- ETags and `If-Match`
- rate limits
- security-event logging
- idempotent export creation
- account-deletion scheduling and outbox jobs
- problem JSON and stable problem codes
- camelCase JSON contract
- existing PostgreSQL tables

## Still not cut over

Render still runs FastAPI. Django exposes the same migrated paths only when running the Django server.

Work, Focus, Execution, and Analytics remain FastAPI migration targets for later phases.

## New compatibility gates

```bash
PYTHONPATH=src uv run python scripts/django_phase3_contract.py
PYTHONPATH=src uv run python scripts/django_phase3_auth_smoke.py
```

The contract check compares every Auth/User path, method, operationId, and public/protected status
against the canonical FastAPI OpenAPI.

The smoke test exercises real Django ORM writes against the Alembic-owned test schema.

## Deployment rule

Do not change Render to Django until Phase 3 plus the remaining domain migrations are complete.
