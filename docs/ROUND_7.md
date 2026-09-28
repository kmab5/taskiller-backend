# Round 7 — Privacy & Operations

Round 7 adds the production lifecycle primitives that sit around Taskiller's core work/focus/execution model.

## Delivered

- asynchronous user data exports with idempotent creation and short-lived signed download URLs;
- export payloads that omit passwords, refresh/reset/verification credentials and internal job/rate-limit state;
- `DELETE /api/v1/me` account-deletion scheduling with `If-Match`, immediate user/session deactivation and delayed hard deletion;
- PostgreSQL `outbox_jobs` worker queue with `FOR UPDATE SKIP LOCKED`, leases, expired-lease recovery, bounded exponential retry and dead-letter state;
- database-backed fixed-window rate limiting for registration, login, password-reset requests, export requests and account deletion;
- append-only `security_events` storing HMAC-pseudonymized network subjects rather than raw IP addresses;
- retention cleanup for expired idempotency/auth tokens, rate-limit buckets, export payloads, old audit events, deletion tombstones and completed/dead jobs.

Account deletion is deliberately asynchronous. Credentials are revoked immediately; the hard-delete job becomes eligible after `account_deletion_grace_days`. The deletion-request tombstone has no user foreign key so completion can be audited briefly after the user row is removed.

The worker is started separately from the API with `python -m taskiller.operations.worker`. A worker instance also ensures one recurring retention job exists.
