# Observability

Use Render logs and existing provider metrics; no additional paid monitoring service is required. Keep external five-minute uptime checks enabled and alert on failed probes.

Every response has a validated or generated `X-Request-ID`; Problem responses include the same `requestId`. Structured HTTP completion logs contain path, status, and duration. They omit query strings, headers, cookies, and client IP. Django request objects are excluded from JSON logs, and raw Uvicorn access logs are disabled to avoid exposing signed export URLs. Worker failure messages and persisted errors contain exception class names only.

`/health/live` confirms the API process; `/health/ready` checks database access and pending migrations. `/health/version` provides package/release identity from Render or `TASKILLER_RELEASE_*`. Supervision exits the service when either child exits; a stalled live worker still needs queue-age investigation.

Useful checks include repeated readiness failures, 5xx responses, request durations, Render restarts/memory, Neon connections, dead jobs, oldest due job, and overdue deletion jobs. Current health responses do not expose queue contents or assert mail-provider delivery.

Security events are a separate pseudonymized PostgreSQL audit history, immutable except for controlled retention. Do not add request bodies, authentication headers, reset tokens, or signed download URLs to logs during incident investigation.
