# Security Baseline

## Authentication

- Argon2id password hashes.
- Short-lived signed access JWTs.
- Opaque rotating refresh credentials, stored only as keyed hashes.
- Refresh-token reuse revokes the device session family.
- Access authorization checks the server-side session on every protected request, so logout/revocation is immediate rather than waiting for JWT expiration.
- Password reset revokes existing sessions.

## HTTP boundary

- Explicit trusted Host allowlist.
- Credentialed CORS with explicit origins; deployed wildcard origins are rejected at startup.
- Secure/HttpOnly refresh cookie in staging/production.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, restrictive Permissions Policy.
- HSTS in production.
- API responses are `Cache-Control: no-store` by default.
- Structured problems never include Python exception messages for unexpected failures.

## Mutation safety

- `If-Match` ETags guard mutable versioned resources.
- `Idempotency-Key` guards retryable creation/event mutations.
- PostgreSQL constraints/triggers independently enforce critical ownership/hierarchy/session invariants.
- Sensitive public auth endpoints use PostgreSQL-backed rate limiting.

## Proxy/IP trust

Koyeb documents that it appends the connecting client IP to `x-forwarded-for` and that the **last** entry is the one it can certify. `TASKILLER_TRUST_FORWARDED_FOR=true` therefore uses only the final entry. Leave this setting false when not behind a trusted proxy with equivalent semantics.

## Authentication email

Production requires a real SMTP transport. SMTP delivery runs off the event loop using a worker thread and never logs one-time tokens. Staging may intentionally use the token-free safe-log sink; local development can use the development sink that exposes tokens.

## Secret handling

Never commit production secrets. Use Koyeb Secrets/environment variables. JWT signing and token-HMAC secrets must be independent. Data exports exclude password hashes, token hashes, one-time auth tokens, rate-limit state and job internals.

## Remaining operational responsibility

Application security does not replace database backups, secret rotation, dependency updates, DNS/TLS configuration, least-privilege Koyeb/Neon accounts, or incident monitoring. Those are release operations, not API features.
