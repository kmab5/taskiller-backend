# Round 2 — Identity & Authentication

## Scope delivered

Round 2 turns the Round 1 infrastructure into a real multi-client identity layer.

### Database

The first migration creates:

- `users`
- `user_preferences`
- `auth_sessions`
- `refresh_tokens`
- `email_verification_tokens`
- `password_reset_tokens`

Deletion cascades are explicit, one-time credential digests are unique, session/token lookup indexes are present, and preference range invariants are duplicated at the database boundary where appropriate.

### Account lifecycle

Registration creates a user, default preferences, one device session and one refresh credential atomically. Email uniqueness is enforced in PostgreSQL as well as surfaced as a `409` API problem.

Login locks the user row before verifying and creating a session. Password reset locks the same row before replacing the password and revoking all sessions; this prevents a stale-password login from committing concurrently with a reset.

### Session security

Access JWTs identify a specific `sid`. Protected requests resolve that session from PostgreSQL, giving logout/device revocation immediate effect. Refresh tokens are one-time credentials and only their keyed digests are stored. Replay of an already-rotated credential revokes the corresponding session family.

### Profile/preferences concurrency

`GET /me` and `GET /me/preferences` return ETags. Mutations require `If-Match`, and the resource version increments on changes. The Work/Focus/Execution rounds will use the same optimistic-concurrency convention.

### Error contract

Authentication and user routes use `application/problem+json`-style bodies with stable machine-readable `code` values. Validation errors intentionally omit submitted input values so passwords/tokens are not reflected in error payloads.

## Intentionally deferred

- production email provider adapter
- login/reset rate limiting (Round 7)
- account export/deletion lifecycle (Round 7)
- OAuth/passkeys/MFA (post-v1 unless promoted)

## Verification

Round 2 includes:

- pure unit tests for password hashing, JWT validation, token hashing, schemas/config and ETags;
- PostgreSQL integration tests for registration, profile concurrency, verification, rotation/reuse detection, password reset, session revocation and preferences;
- CI migration-before-test ordering;
- generated OpenAPI from the actual FastAPI app.
