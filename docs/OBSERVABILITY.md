# Observability

Taskiller v1 deliberately uses platform-native metrics plus structured application logs instead of adding a metrics backend before one is needed.

## Request correlation

Every HTTP response includes:

```text
X-Request-ID: <opaque id>
```

Clients may provide a safe 8–128 character `X-Request-ID`; otherwise Taskiller generates one. Problem responses also include the same value as `requestId`.

## Structured logs

HTTP completion logs are JSON and include:

- `request_id`
- HTTP method
- URL path (never query strings/tokens)
- status code
- duration in milliseconds
- normalized client IP

Unhandled exceptions are logged with request ID and path; the client receives only a sanitized internal-error problem.

Security events are a separate append-only PostgreSQL audit trail. They store HMAC-pseudonymized subjects, not raw IP addresses.

## Release identity

`GET /health/version` returns package version plus Git SHA/branch/repository when supplied by Koyeb or `TASKILLER_RELEASE_*` environment variables.

## Alerting baseline

For a production service, alert on:

- sustained `/health/ready` failure;
- HTTP 5xx rate;
- p95/p99 request latency;
- Koyeb instance restarts or memory saturation;
- Neon connection/compute saturation;
- `outbox_jobs.status='dead'` count > 0;
- old `running` jobs whose leases repeatedly expire;
- account deletion jobs reaching `dead`;
- repeated rate-limit spikes on authentication scopes.

Koyeb exposes service logs and resource/request metrics. If long-term log retention is required, use Koyeb's log exporter or another external collector; the application emits machine-readable JSON already.
