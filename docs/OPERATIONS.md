# Operations

## API and worker

The FastAPI service remains stateless. Background work uses PostgreSQL, so v1 does not require Redis or another broker. Run at least one worker process alongside the API:

```bash
PYTHONPATH=src python -m taskiller.operations.worker
```

Workers claim eligible jobs with `FOR UPDATE SKIP LOCKED`, increment the attempt counter, and hold a bounded lease. On process loss, the next worker recovers expired leases. Failed jobs use bounded exponential retry and become `dead` after `outbox_max_attempts`.

## Exports

`POST /api/v1/me/export-requests` queues a gzip-compressed JSON export. `GET /api/v1/me/export-requests/{id}` returns status and, when ready, a short-lived HMAC-signed download URL. Export bytes live in PostgreSQL only for the configured TTL; object storage can replace this later without changing the request/status API.

## Account deletion

`DELETE /api/v1/me` requires the current user ETag. Taskiller marks the user inactive and revokes every auth session in the same transaction, then queues hard deletion after the configured grace period. Cascading FKs remove user-owned domain data. A minimal deletion tombstone and security events survive only for their retention windows.

## Rate limiting and audit

Sensitive unauthenticated routes use PostgreSQL fixed-window counters keyed by HMAC(subject), not plaintext IP/email. Test environments skip limits unless `rate_limit_test_mode=true`. Security events are append-only; retention is the only database-authorized delete path.
