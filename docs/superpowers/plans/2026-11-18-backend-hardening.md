# Backend Hardening Implementation Plan

## Goal and constraints

Implement the relevant findings from the backend audit without adding paid services. Keep Render Free with externally configured five-minute uptime checks, Neon, Vercel, and Mailjet. Django is authoritative; no pre-transition real-user migration guarantee is required. Preserve API shapes and safely refuse conflicting schema data instead of deleting it implicitly.

## Work packages

- [x] Database: add current Django constraints/indexes and ownership/hierarchy guards in forward migrations; test real PostgreSQL invariants and account deletion.
- [x] Authentication: trusted browser origins, independent abuse budgets, cheap invalid-token rejection, durable email jobs that never store raw tokens, strict provider acceptance.
- [x] Worker: supervise processes, reconnect/recover periodically, fence claims, atomically acknowledge effects, maintain retention scheduling, export a consistent snapshot, explicitly remove account dependencies.
- [x] Domain/API: consistent locking, Work Type detachment, linked-item revalidation, robust cursor decoding, and portable header documentation.
- [x] Operations: refresh vulnerable lock entries, correct PostgreSQL 18 volume layout, serialize startup migrations, configure ASGI connections/logging, fix smoke query encoding, expand CI and update stale runbooks.
- [x] Verification: focused regressions, 150 full-suite tests, migrations/drift/catalog audit, contract checks, domain smokes, lint/format/typecheck/compile, and dependency audit pass. Native launcher checks pass; Docker engine is unavailable locally.

Delivery follows final diff review: commit and push the validated backend changes, reporting the exact commit and hosted-only verification limits in the implementation response.

## Test environment

Use only disposable local PostgreSQL on 127.0.0.1:55432 with explicit environment overrides. Integration tests use isolated transactions and skip when no test URL is provided. External email transports are stubbed. No production account, secret, database, or provider state is needed.

## Acceptance

Duplicate identity/open-session rows are rejected by PostgreSQL; complete account deletion succeeds; untrusted browser login is rejected; invalid reset tokens do not hash passwords; jobs recover after lease expiry and stale claims cannot acknowledge them. Existing public happy paths remain compatible. Five-minute uptime checks remain an operational assumption, with outage recovery documented.
