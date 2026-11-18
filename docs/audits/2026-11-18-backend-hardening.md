# Backend Audit Remediation — 2026-11-18

## Deployment assumptions

The owner confirmed an entirely no-cost implementation: Render Free with external five-minute uptime checks, an embedded PostgreSQL worker, Neon, Mailjet, and a Vercel frontend. FastAPI was replaced before real users existed. These changes retain that topology and prioritize the current Django schema; they add no paid service and do not reset any database.

## Audit finding disposition

| Finding | Change |
| --- | --- |
| B01: schema integrity | Forward migrations add case-insensitive identity/slug uniqueness, one-open-session exclusivity, token/event/segment uniqueness, state/version checks, ownership/hierarchy guards, immutable history, and queue/retention indexes. Session start also returns an explicit open-session conflict. |
| B02: deletion | Explicitly remove dependent events, reviews, sessions, plan segments/plans/recommendations, work hierarchy/types, credentials, preferences, exports, and replay records; retain the intended deletion tombstone/security history. Clear refresh rotation references before removal. |
| B03: worker liveness | The launcher supervises both children and cleans up on failure; worker database failures close stale connections and retry. |
| B04: abandoned leases | Recover expired leases every 15 seconds and enforce retry ceilings/resource failure status. |
| B05: Render sleep | Owner-confirmed five-minute external checks are the operating assumption. Preserve Free hosting, document monitor outage/recovery behavior, and remove the paid-worker recommendation. No uptime-monitor configuration was changed. |
| B06: login CSRF | Reject untrusted Origin on cookie-setting/auth endpoints; permit deliberate native requests without Origin unless browser Fetch Metadata indicates cross-site. |
| B07: reset hashing | Reject invalid/expired/consumed credentials before Argon2, throttle confirmations, and revalidate under lock before applying a password. |
| B08: registration abuse | Add an independent IP budget before account creation and hashing. |
| B09: mail abuse | Add confirmation/delivery budgets and per-user cooldown; reset delivery also has a recipient budget. |
| B10: job consistency | Fence claims with a unique claim token; commit database effects and acknowledgement together. Stale claims cannot acknowledge/fail reclaimed jobs. Retention successors are idempotently scheduled. |
| B11: retention liveness | Periodic maintenance independently ensures a retention job exists, including after exhausted failures. |
| B12: export consistency | Build exports under a fresh repeatable-read transaction; archive and job success commit together. |
| B13: reorder deadlock | Acquire the owner namespace before idempotency/resource/sibling locks across work, focus, execution, portable import, and export creation. |
| B14: Work Type deletion | Detach references, including soft-deleted Work Items, and increment affected item versions/timestamps before deleting a custom type. |
| B15: stale plan links | Revalidate linked items' ownership, live state, terminal state, and current target relationship at session start. |
| B16: malformed cursors | Validate decoded container, exact shape, scalar types, timestamp timezone, and UUID across execution/focus/work decoders. |
| B17: portable contract | Declare the required 8–200 character Idempotency-Key in Django metadata and canonical OpenAPI; test it alongside actual auth-response schema validation. |
| B18: vulnerable packages | Update certifi to 2026.10.23 and dnspython to 2.9.2; locked runtime dependency auditing is now a CI gate. |
| B19: local persistence | Mount PostgreSQL 18's volume at /var/lib/postgresql. Existing local data requires an intentional backup/move; no volumes were deleted. |
| B20: mail durability | Atomically enqueue token references with token hashes; reconstruct domain-separated HMAC tokens at delivery, retry provider failure, preserve prior usable links, and consume sibling tokens on confirmation. Require explicit Mailjet acceptance. |

## Supporting changes

- Serialize startup migrations using a transaction-scoped advisory lock compatible with Neon's transaction pooler; test failure rollback and startup from an empty database.
- Audit actual PostgreSQL constraints/indexes/triggers instead of accepting migration history alone. Regression tests deliberately remove an index/trigger inside a rolled-back transaction to verify detection.
- Disable persistent per-thread ASGI database connections; load local environment consistently without overriding supplied environment variables.
- Configure JSON logs, omit raw request objects/query strings, and disable raw Uvicorn access logs so signed export credentials are not logged. Worker errors persist exception class names only.
- Fix ISO timestamp query encoding in the privacy smoke and process earlier queued jobs before asserting its export completes.
- Run all domain and privacy/worker smokes in CI; add local-database guards for integration tests and importlib test discovery for matching unit/integration filenames.
- Refresh Render/Django production, operations, observability, security, rollback, environment, and contributor/context documentation. Ignore generated staticfiles. Historical FastAPI validation is superseded by current validation; the original audit remains a dated record.

## Validation and limits

Validation commands and final measured results are recorded in root `VALIDATION.md`. Verification uses only disposable local PostgreSQL and stubbed mail transports. The production launcher was also exercised over local HTTP: readiness 200, trusted-origin preflight 204, untrusted-origin login 403, and 30 concurrent health requests without failure. Deliberately terminating its API child caused the supervisor to exit and clean up the worker.

No hosted database, Render settings, real mail delivery, or frontend repository was changed. Pending mail is at-least-once delivery; a crash after provider acceptance can produce a duplicate link. Process supervision detects exit, not every stalled live process. The external monitor still needs to remain enabled; outages resume work rather than guarantee exact deadlines. Pyright coverage remains intentionally limited to the configured framework-neutral modules. Docker image execution requires a running engine and remains an explicit verification limitation if unavailable.

Frontend contract snapshots should be refreshed through the frontend's documented api:update workflow when coordinating this backend release. The backend now accurately documents the already-required import header and origin rejection; API request/success response shapes remain stable.
