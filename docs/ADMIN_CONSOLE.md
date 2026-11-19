# Administrative console contract and operations

This reference covers the dedicated staff console at `/api/v1/admin/`. The
[product field guide](index.html) covers product operations only. The canonical
machine-readable contract is [openapi/current.json](../openapi/current.json), served
at `/openapi.json`. Generate additive admin definitions with
`python scripts/build_admin_contract.py`; this reads source with AST and does not
import Django, connect to a database, or load deployment configuration.
Use `--update-problem-codes` when intentionally adding literal runtime error codes
to `src/taskiller/core/problems.py` before generating the canonical catalog.

## Identity and capability boundary

Console identities are individually enrolled active Django staff users. Product
`TaskillerUser` accounts, product bearer tokens, Django Admin cookies, and pending
MFA challenges do not authorize console reads. Django superuser status alone does
not grant a console role. `/admin/` on the Django host remains the separate internal
Django Admin diagnostic interface; it is not the frontend console.

Dedicated groups use `taskiller-console:` followed by the exact role name. Named
permissions use `django_domain.console_<capability>`.

| Role | Capabilities |
| --- | --- |
| Owner | All capabilities listed below |
| Administrator | `view_users`, `view_activity`, `manage_accounts`, `retry_jobs`, `view_audit`, `view_overview`, `view_jobs`, `recovery_email` |
| Support | `view_users`, `view_activity`, `recovery_email` |
| Analyst | `view_overview` |

The complete set is `view_users`, `view_activity`, `read_private`,
`manage_accounts`, `manage_privacy`, `retry_jobs`, `manage_staff`, `view_audit`,
`view_overview`, `view_jobs`, and `recovery_email`. Explicit individual grants are
limited to `read_private` and `manage_privacy`; Owner receives both through its role.
Use `me.capabilities` for navigation, and handle backend denial independently on
every request. List scopes apply before pagination and counting.

Staff invitation, role changes, and revocation require `manage_staff`. Prevent
self-grants and removal or disablement of the last eligible Owner. All eligibility
and membership changes, including CLI recovery, serialize through the shared Owner
transaction lock. Changing roles or revoking access invalidates existing sessions
and pending challenges. Fresh MFA is required within five minutes for staff
changes, suspension/reactivation, private work reads/corrections, and privacy
operations. Work corrections additionally require `manage_accounts`.

## Frontend relay handoff

Use a fixed server-only Django origin and an explicit route/method allowlist. Map
`/admin/api/<relative-path>` on the SvelteKit host to
`/api/v1/admin/<relative-path>` on Django. Do not forward browser-controlled target
URLs, product Authorization headers, product cookies, or the Django Admin session.
Do not follow upstream redirects. Bound body sizes and upstream timeouts.

| Cookie | Browser contract |
| --- | --- |
| `taskiller_staff` | Opaque authenticated session; HttpOnly |
| `taskiller_staff_csrf` | Dedicated CSRF cookie; use the masked bootstrap token for requests |
| `taskiller_staff_challenge` | Short-lived browser binding for pending MFA/enrollment; HttpOnly |

Authenticated sessions have a 30-minute idle limit and an eight-hour absolute
limit. Use `idleExpiresAt` and `expiresAt` returned by `me`; the server remains
authoritative. Last-seen writes are throttled to roughly once per minute.

All three cookies are host-only, scoped to `/admin`, SameSite=Lax, and Secure in
production. The relay must explicitly forward only these cookies and translate
only approved upstream Set-Cookie headers to the frontend host, preserving security
attributes and expirations. The `/admin` path intentionally means these browser
cookies are sent to the relay, rather than directly to `/api/v1/admin`.

1. `GET auth/csrf` obtains a masked CSRF token and the dedicated cookie.
2. Send `X-CSRFToken` and the exact public console `Origin` on every POST/PATCH,
   including anonymous login, MFA and enrollment. The relay rejects cross-origin
   writes and preserves the validated public Origin upstream. Django independently
   verifies the exact allowlist and CSRF pair.
3. Password login creates only a pending challenge. TOTP or a one-time recovery
   code completes MFA and creates the staff session. Staff auth never calls the
   product refresh endpoint.
4. MFA, step-up and enrollment confirmation can append an optional `csrfToken` to
   their typed response through the CSRF helper. Use that fresh token after cookie
   rotation, or re-fetch `auth/csrf`. `GET me` shares the staff response shape but
   need not include this field. Forward logout cookie expiration even with a 204.
5. Treat 401 as an expired/invalid session: clear privileged queries and return to
   console login. Treat 403 as denied capability, required step-up, disabled
   console, or disabled writes according to the Problem Details code.

Forward applicable `Content-Type`, `X-CSRFToken`, `Origin`, `If-Match`, and
`Idempotency-Key` request headers. Preserve status, Problem Details, `ETag`,
`Cache-Control`, `Retry-After`, and request identifiers, plus approved cookies.
Never serialize staff credentials into page data or browser storage. Render admin
pages, data responses and redirects with `Cache-Control: private, no-store`,
`Referrer-Policy: no-referrer`, and noindex. Exclude the exact `/admin` boundary
from service-worker caches and purge old admin entries. Keep email searches in
POST bodies and out of URLs, logs, referrers and telemetry.

## Endpoint families

All paths here are relative to `/api/v1/admin/`; see the canonical contract for
exact field names, response status codes, and typed schemas.

| Family | Operations |
| --- | --- |
| Authentication | `GET auth/csrf`; `POST auth/login`, `auth/mfa`, `auth/logout`, `auth/step-up`; `GET me` |
| Enrollment | `POST auth/enroll`, `auth/enroll/confirm`; browser-bound, expiring and single-use |
| Account reads | `GET overview`, `users`, `users/{id}`, `users/{id}/activity`, `users/{id}/sessions`; `POST users/search` |
| Operational reads | `GET jobs`, `privacy/requests`, `audit`, `staff`, `roles` |
| Account commands | `POST users/{id}/suspend`, `reactivate`, `recovery-email`, `revoke-sessions` |
| Queue commands | `POST jobs/{id}/retry` |
| Staff commands | `POST staff/invitations`; `PATCH staff/{id}/roles`; `POST staff/{id}/revoke-access` |
| Private work | `GET users/{user_id}/work`, `work/{work_id}`; `POST work/{target_id}/correct` |
| Privacy | `GET privacy/requests/{request_id}`; `POST users/{target_id}/privacy/export`, `users/{target_id}/privacy/deletion` |
| Bulk | `POST bulk/preview`, `bulk/execute`; per-target eligibility/outcomes |

Reads use UTC ranges of at most 90 days (default 30), a default page size of 25,
and a maximum of 100. Cursors are opaque, expiring, and bound to the query/scope;
reset them when filters change. User search requires at least three characters and
uses exact email or anchored display-name matching. Use `POST users/search` when
the query may contain an email address. Search requires CSRF but does not mutate
account state. Session last-used time, execution events and registration time are
different recorded signals; none establishes live presence.

Overview counts registrations by creation timestamp, completed Execution Sessions
by completion timestamp, and distinct accounts with recorded execution events in
the selected window. Operational counts are capability scoped. A null metric or
worker timestamp means unavailable/unobserved, not zero or confirmed worker health.
General projections omit credentials, private descriptions, review notes, raw job
payloads, provider failures and security-event metadata. Private and privacy reads
are separately authorized and audited. No console route downloads an export secret.
Private work lists retain minimal metadata. Individual work detail can include
allowlisted descriptions, scheduling fields, Work Type characteristics, ordered
Focus Plan segments and recorded execution timestamps, according to its kind.
It does not include review notes, arbitrary model fields, or raw event payloads.

## Command semantics

Every command requires a structured `reason` with a lower-case identifier `reasonCode`
(2–64 characters, letters/digits/underscore, beginning with a letter) and an optional
comment of at most 500 characters. Do not include private notes or credentials in
comments. Commands use `Idempotency-Key`; retain the same key and identical payload
and precondition for retries of the same intent. Receipts bind actor, operation,
target, payload and precondition. Replays recheck current authorization. A changed
payload with the same key returns 409. Invitation credentials are shown once and
are excluded from audit/receipt persistence; a replay cannot recover that secret.

Account suspend/reactivate, staff role/revocation, versioned work corrections and
account deletion use the latest detail `ETag` as `If-Match`. Preserve its quoted
value exactly. Missing and stale preconditions return 412 `precondition_failed`;
re-fetch and review before submitting another intent. A successful response may
return a replacement ETag; invalidate affected queries.

Suspension revokes product sessions and prevents login/refresh. It does not stop
an already-running Execution Session. Use a separate mapped domain event to change
execution state. Reactivation only applies to an eligible suspended account and
does not revive revoked sessions. Pending deletion blocks suspension/reactivation.
Recovery-email responses indicate queue acceptance or suppression, never delivery.
Revocation can name one `sessionId` or omit it to revoke all account sessions.

Job retries are conservative: only failed, explicitly eligible data-export jobs
can be reset, after checking the export and account under locks. Never blindly
replay mail, completed work, or deletion jobs. Privacy commands reuse the existing
export/deletion flows and require explicit privacy access and fresh MFA.

Work corrections map to `update-item`, `update-type`, `update-plan` or
`session-event`, with existing typed domain payloads. They do not support arbitrary
database editing, historical event rewriting, impersonation, or system Work Type
mutation. Staff events use server timestamps.

Bulk requests contain at most 50 unique targets. Account actions use their bare
action names; other supported actions are `staff.roles`, `staff.revoke-access`,
`jobs.retry`, `privacy.export`, `privacy.deletion` and `work.correct`. Targets can
carry `etag`, `sessionId`, `roles`, or a typed `operation`/`correction` as applicable.
Preview is advisory; execute repeats authorization, state and ETag checks and returns
explicit partial results. Retrying one failed target uses its original intent and
precondition only after reviewing its outcome. Successful mutations, redacted audit
rows and receipts commit together; rollback leaves no success record. Denied/failed
security events are recorded separately. Audit history is append-only for the
application; retention is an operator-controlled database procedure.

## Deployment, bootstrap and recovery

Keep Render Free with the embedded worker, Neon, Mailjet and Vercel. No additional
service is required. Apply additive Django migrations before enabling access.

| Environment setting | Initial value/purpose |
| --- | --- |
| `TASKILLER_ADMIN_CONSOLE_ENABLED` | `false`; controls console access |
| `TASKILLER_ADMIN_CONSOLE_WRITES_ENABLED` | `false`; independent command rollout switch |
| `TASKILLER_ADMIN_CONSOLE_ORIGINS` | JSON list of exact public console origins; no wildcard |
| `TASKILLER_ADMIN_CONSOLE_ENCRYPTION_KEYS` | Deployment-held comma-separated Fernet keys, newest first |
| `TASKILLER_ADMIN_CONSOLE_COOKIE_SECURE` | `true` in production |

Bootstrap a named active Django staff identity as Owner with the dedicated command:

```powershell
$env:PYTHONPATH = "src"
uv run python manage.py bootstrap_staff_console --username operator --reason "Initial Owner enrollment"
```

It outputs one single-use enrollment token, valid for one hour. Transfer it directly
to the intended operator, submit it with a new password to `auth/enroll`, and
confirm the returned challenge using TOTP at `auth/enroll/confirm`. Intake returns
`secret` and `provisioningUri` only to initialize the authenticator. Confirmation
returns one-time `recoveryCodes`; retain them offline and discard the displayed
seed. These are authentication ceremony fields, never directory or audit fields.
Enrollment confirmation does not create a full staff session; proceed to password
login and MFA after saving the recovery codes.
The existing `bootstrap_taskiller_admin` command and
`TASKILLER_ADMIN_USERNAME/EMAIL/PASSWORD` variables create the separate Django Admin
identity; they do not enroll a console Owner. Do not put a bootstrap password,
invitation credential, encryption key, TOTP seed or recovery code in Git or logs.

Recover lost MFA through the same command with `--recover-mfa` and a required reason,
revoking sessions and pending challenges before reenrollment. Offboard by revoking
console access; retain durable audit identifiers. Establish a second individually
enrolled Owner before routine offboarding, while preserving the last-Owner guard.
Rotate encryption keys by retaining old decryption keys until enrolled secrets are
reencrypted; removing the only usable key makes existing MFA unavailable.

Bootstrap the first Owner while access remains disabled, then enable read access
to complete MFA enrollment and deployment verification with writes disabled. Enable writes
after an actual relay/cookie/CSRF smoke check and one audited authorized mutation
through the deployed topology. Roll back commands first by disabling the write
flag, then disable access if needed; retain migrations, sessions and audit history.
Do not restore the historical FastAPI runtime or regenerate the Django baseline.

For this implementation, no local checks or tests are authorized. After coding is
complete, GitHub CI owns migration drift, security regressions, cutover parity,
static contract freshness, lint/type checks, PostgreSQL tests and release checks.
Inspect Render migration/startup logs and deployed revision/readiness before
rollout. Frontend snapshot/type generation and deployed browser verification belong
to the frontend integration slice. Report unavailable CI/log access explicitly.
