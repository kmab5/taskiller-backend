# Authentication Architecture

Taskiller authentication is owned by the Python/FastAPI backend. There is no external auth service in the v1 architecture, so every client (web, Android, iOS, desktop, CLI) uses the same Taskiller REST API for identity and session operations.

## Chosen primitives

- Password hashing: Argon2id through `pwdlib[argon2]`.
- Access tokens: short-lived signed JWTs through `PyJWT`.
- Refresh tokens: high-entropy opaque random tokens. Only a cryptographic hash is stored server-side.
- Refresh rotation: every successful refresh replaces the presented token.
- Reuse detection: replay of a rotated refresh token revokes its token family so a stolen token cannot silently remain active.
- Account/session state: PostgreSQL.
- Email verification and password reset: single-use, expiring opaque tokens stored hashed. Delivery is behind an email-provider interface so development can use a local sink and production can choose a provider later.

FastAPI's current security documentation recommends `PyJWT` for JWT handling and `pwdlib` with Argon2 for password hashing; Taskiller follows that direction while adding persistent refresh-session rotation for multi-device clients.

## Planned endpoints

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
POST /api/v1/auth/logout-all
GET  /api/v1/auth/sessions
DELETE /api/v1/auth/sessions/{session_id}

POST /api/v1/auth/email/verify/request
POST /api/v1/auth/email/verify/confirm
POST /api/v1/auth/password/forgot
POST /api/v1/auth/password/reset

GET   /api/v1/me
PATCH /api/v1/me
```

Exact request/response shapes are implemented and contract-tested in Round 2.

## Access-token rules

Access JWTs are authorization credentials, not user-profile storage. The minimal claims are:

- `sub`: Taskiller user UUID
- `sid`: refresh-session UUID
- `iat`: issued-at timestamp
- `exp`: expiry timestamp
- `iss`: Taskiller issuer
- `aud`: Taskiller API audience
- `jti`: unique token identifier

The API resolves the current user from `sub`; it never accepts a client-supplied user ID as proof of ownership.

## Refresh-token rules

A refresh token is returned only when created or rotated. The plaintext value is never persisted or logged. A database row stores its hash, session/family identity, timestamps and revocation state. A successful refresh is transactional: validate the current token, mark it rotated, create its successor and issue a new access token. Reuse of an already-rotated token invalidates the family.

## Web versus native clients

The REST contract is client-independent. Web integration may transport refresh credentials with a secure HTTP-only cookie while native clients use secure platform storage; both map to the same backend session model. Access tokens are sent as `Authorization: Bearer <token>`.

## Deferred integrations

These do not block the v1 backend foundation:

- Google/Apple/GitHub OAuth
- passkeys/WebAuthn
- MFA
- production email provider selection

They must attach to the same Taskiller user/session model rather than creating a second identity system.
