# Administrative Console Backend Implementation Plan

**Goal:** Implement every backend workflow in plan/admin/backend-admin.md without frontend dependencies.
**Architecture:** Dedicated opaque-cookie staff sessions, encrypted TOTP, Django permission groups, transactional audit and commands; additive PostgreSQL migrations. Product authentication remains separate.
**Validation constraint:** Write backend tests while implementing, but execute checks only in GitHub CI after coding is complete. No local browser, Playwright, or frontend tests. Observe Render deployment logs at the end when accessible.

- [x] Add enrollment, challenge, session, recovery, audit and command receipt models and migrations; product suspension state.
- [x] Implement central capability/step-up policy, strict-origin CSRF, password/MFA/enrollment/recovery flows and CLI owner bootstrap/recovery.
- [x] Implement bounded allowlisted overview, directory, activity, sessions, jobs, privacy, audit, staff, roles and private work reads.
- [x] Implement audited reasoned ETag/idempotent account, staff, queue, privacy and mapped work commands, plus bounded bulk preview/execution.
- [x] Publish typed canonical OpenAPI and operator/relay documentation; retain disabled-by-default read/write switches.
- [x] Write backend security and PostgreSQL regression tests and CI coverage. Review implementation before the first check run.
- [ ] Commit/push completed implementation for GitHub CI; investigate failures there and inspect Render logs without requiring frontend implementation.

## Integration interfaces

Models: StaffEnrollment(id UUID, user FK Django User, enabled, mfa_secret_encrypted, last_totp_step, version, created_at, updated_at), StaffChallenge(id, enrollment nullable FK, secret_digest, purpose, expires_at, consumed_at, attempts, payload_json), StaffSession(id, enrollment FK, token_digest, auth_hash, created_at, last_seen_at, expires_at, mfa_verified_at, revoked_at, version), StaffRecoveryCode(id, enrollment FK, code_digest, used_at), AdminAuditRecord(id, actor_id nullable string, action, target_type, target_id, created_at, request_id, outcome, reason_code, comment, changes_json), AdminCommandReceipt(id, actor_id UUID, action, target_id, key_digest, request_hash, response_json, created_at). All UUID IDs have uuid4 defaults; timestamps default timezone.now.

AdminAPIView in admin_api/authentication.py: per-view capability string, step_up boolean; request.user is Django staff User and request.auth is StaffSession. Central policy in permissions.py exports require_capability(request, action, step_up=False, target=None), effective_capabilities(user), ROLE_CAPABILITIES, OWNER_LOCK_ID, owner_lock(), ensure_not_last_owner(enrollment). Actions must recheck after locks.

Audit helper in audit.py: record(request, action, target_type='', target_id='', outcome='success', reason=None, changes=None). Store only allowlisted redacted changes and independent IDs.

Role names: Owner, Administrator, Support, Analyst. Capability identifiers: view_users, view_activity, read_private, manage_accounts, manage_privacy, retry_jobs, manage_staff, view_audit, view_overview, view_jobs. Dedicated group prefix taskiller-console:. Django permissions use django_domain.console_<capability>. Owner gets all. Administrator gets all except manage_staff, read_private, manage_privacy. Support gets view_users, view_activity, recovery_email. Analyst gets view_overview. Additional explicit grants read_private/manage_privacy are user permissions.

Settings in Django settings: ADMIN_CONSOLE_ENABLED/ADMIN_CONSOLE_WRITES_ENABLED (default false), ADMIN_CONSOLE_ORIGINS (exact JSON origins), ADMIN_CONSOLE_ENCRYPTION_KEYS (comma separated Fernet keys), ADMIN_CONSOLE_COOKIE_SECURE. Environment prefix TASKILLER_. Cookies taskiller_staff and taskiller_staff_csrf, path /admin, SameSite=Lax, Secure in production. MFA challenge browser cookie taskiller_staff_challenge.
