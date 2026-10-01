# Security Baseline

## Authentication

- Argon2id password hashes.
- Short-lived signed access JWTs.
- Opaque rotating refresh credentials, stored only as keyed hashes.
- Refresh-token reuse revokes the device session family.
- Access authorization checks the server-side session on every protected request.
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

Production runs behind Render. `TASKILLER_TRUST_FORWARDED_FOR=true` allows the runtime middleware to use the forwarded client-address chain supplied by the trusted deployment proxy. Leave this disabled when running behind an untrusted or unknown proxy.

## Authentication email

Production requires a real delivery transport. The recommended zero-cost Render setup uses Mailjet Send API v3.1 over HTTPS. API credentials remain server-side only and one-time authentication tokens are never logged in production. Provider errors are normalized to `email_delivery_unavailable`.

SMTP remains available as an alternative transport for environments where outbound SMTP is allowed.

## Secret handling

Never commit production secrets. Store JWT/token-HMAC secrets and Mailjet credentials in Render's environment configuration. JWT signing and token-HMAC secrets must be independent. Data exports exclude password hashes, token hashes, one-time auth tokens, rate-limit state, and job internals.

## Remaining operational responsibility

Application security does not replace database backups, secret rotation, dependency updates, DNS/TLS configuration, least-privilege provider accounts, or incident monitoring.
