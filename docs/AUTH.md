# Authentication Architecture

Taskiller authentication is owned by the Python/FastAPI backend. Every client — web, Android, iOS, desktop, CLI — uses the same REST API and the same server-side session model.

## Primitives

- **Passwords:** Argon2id through `pwdlib[argon2]`.
- **Access credentials:** signed HS256 JWTs through PyJWT, 15 minutes by default.
- **Refresh credentials:** 384-bit opaque random tokens. Plaintext is returned only as an HttpOnly cookie; PostgreSQL stores only an HMAC-SHA256 digest under an independent token-hash secret.
- **Device sessions:** persistent PostgreSQL rows. Every authenticated API request validates both JWT claims and the referenced session, so explicit session revocation invalidates access immediately rather than waiting for JWT expiry.
- **Refresh rotation:** every successful refresh consumes the presented token and creates a successor.
- **Reuse detection:** presenting an already-rotated refresh token revokes the whole device session/token family.
- **Email verification/password reset:** single-use, expiring opaque tokens stored only as keyed digests.

FastAPI's current security documentation uses PyJWT and recommends `pwdlib` with Argon2 for password hashing; Taskiller adds persistent device sessions and refresh rotation on top of those primitives.

## Access JWT claims

Taskiller access JWTs contain only authorization identifiers and timestamps:

- `sub` — user UUID
- `sid` — device/auth-session UUID
- `jti` — unique access-token UUID
- `iat`, `nbf`, `exp`
- `iss`, `aud`

Profile data is never trusted from token claims. The server resolves the user and active session from PostgreSQL on protected requests.

## Refresh model

A login or registration creates one `auth_sessions` row and its first `refresh_tokens` row. Rotation is transactional and uses a stable lock order: **auth session → refresh token**.

A valid refresh:

1. hashes the cookie credential;
2. resolves its token row;
3. locks the owning device session;
4. locks and re-validates the token;
5. marks the old token rotated;
6. creates the successor token;
7. updates `last_used_at`;
8. issues a fresh access JWT and refresh cookie.

A replay of a rotated token revokes the device session and all refresh credentials under it. Clients should single-flight refresh requests per device; intentionally concurrent refresh attempts with the same one-time credential are treated as reuse.

## Cookie policy

Refresh credentials are transported as HttpOnly cookies scoped to the auth API path. `SameSite=Lax` is the default and production/staging default to `Secure`. If a future deployment requires `SameSite=None`, configuration validation requires `Secure=true`; a CSRF strategy must also be reviewed before that topology is enabled.

Native apps may use an HTTP cookie jar backed by platform-secure storage. Access JWTs are supplied as `Authorization: Bearer <token>`.

## Endpoints implemented in Round 2

```text
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
POST   /api/v1/auth/logout-all
GET    /api/v1/auth/sessions
DELETE /api/v1/auth/sessions/{sessionId}

POST   /api/v1/auth/email-verification/request
POST   /api/v1/auth/email-verification/confirm
POST   /api/v1/auth/password-reset/request
POST   /api/v1/auth/password-reset/confirm

GET    /api/v1/me
PATCH  /api/v1/me
GET    /api/v1/me/preferences
PATCH  /api/v1/me/preferences
```

The password-reset request endpoint deliberately returns `202` for both known and unknown email addresses. Reset success revokes every active device session. Profile and preference mutations require `If-Match` using the latest ETag.

## Email delivery boundary

The token lifecycle is fully implemented, while the production email vendor remains intentionally unselected. `AuthEmailSender` is the interface boundary:

- local development logs one-time tokens for manual testing;
- integration tests use an in-memory sender;
- production currently uses a token-safe placeholder that never logs secrets.

A real email adapter must be selected before production release (Round 8). Registration itself is not coupled to delivery; clients explicitly request verification after account creation.

## Deferred auth features

Not required for Taskiller v1 core correctness:

- social OAuth
- passkeys/WebAuthn
- MFA

These must attach to the existing `users`/`auth_sessions` model rather than introduce a parallel identity system.
