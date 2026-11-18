# Operations

## API and worker

Run `PYTHONPATH=src uv run python manage.py taskiller_worker` locally. Render runs the same command beside Django in one Free service. Keep external five-minute uptime checks enabled; no separate broker or paid worker is required.

Workers claim due jobs with `FOR UPDATE SKIP LOCKED`, a unique claim token, and a bounded lease. Database effects and success acknowledgement commit together. Stale claimants cannot finish/fail replacement claims. Recovery and retention scheduling run every 15 seconds, including idle polling. Exhausted attempts mark jobs dead and update export/deletion failure status. Database failures close stale connections and retry.

Supervision detects child exits; readiness checks database/migrations. Neither detects every stalled live process. Inspect overdue jobs and logs when business work stops even if HTTP requests succeed.

## Authentication mail

Verification/reset requests atomically create token hashes and `auth_email` jobs. Jobs contain only token ID, user ID, and purpose. The worker reconstructs the token using a domain-separated HMAC and skips expired/consumed tokens or inactive/deleted users. Provider failures retry the same credential; a crash after provider acceptance may deliver a duplicate link. Mailjet must explicitly report success. No raw token is persisted in the queue.

A per-user cooldown and PostgreSQL-backed IP/recipient budgets bound delivery. Resends preserve older usable links until expiration or successful confirmation; confirmation consumes sibling tokens. A 202 means queued or intentionally suppressed, not delivery confirmation. Investigate dead `auth_email` jobs if delivery stops.

## Exports and account deletion

Exports are gzip JSON stored temporarily in PostgreSQL. A repeatable-read transaction collects a consistent dataset and commits the archive with job success. The API issues short-lived HMAC-signed download links; retention clears expired archive bytes.

Account deletion requires a current user ETag, disables the user, revokes sessions, and schedules hard deletion after the grace period. The worker explicitly deletes dependent records in foreign-key order; it does not rely on legacy cascades. A minimal deletion tombstone and pseudonymized security history remain until retention. Delayed jobs resume after outages; free hosting cannot guarantee deadlines while unavailable.

## Retention and investigation

Retention runs daily and is independently re-established if its preceding job dies. It removes expired credentials/replay counters, archive bytes, old security events, tombstones, and finished-job history. Retention explicitly enables deletion of immutable security history; account deletion explicitly enables session-history deletion.

Inspect `outbox_jobs` for dead jobs and running jobs with expired leases. Errors contain exception classes rather than potentially sensitive provider messages. Diagnose the cause before manually requeueing; never reset an in-progress claim. See `RUNBOOK.md` for SQL and release checks.
