# Production Runbook

## Release

1. Merge only a green `main` build.
2. Confirm the committed `openapi/current.json` changed intentionally.
3. Koyeb builds the Dockerfile from the selected Git SHA.
4. Container startup runs `scripts/migrate.py`; advisory locking serializes concurrent migration launchers.
5. Uvicorn starts only after migration succeeds.
6. Koyeb promotes the deployment only when `/health/ready` returns 200.
7. Confirm `/health/version` shows the intended SHA.
8. Run `python scripts/load_smoke.py --base-url https://<api-host>` from an operator machine.

## Migration failure

Do not bypass readiness. Inspect migration/database logs, correct the migration or database condition, and redeploy. The previous healthy Koyeb deployment can continue receiving traffic while a new deployment fails health checks.

## Rollback

Application rollback and schema rollback are separate decisions. Prefer forward-fixing a migrated database. Only run Alembic downgrade after verifying that no data written by the newer release would be lost or become unreadable.

For a code-only rollback, redeploy the prior Git commit **only if its expected schema revision is compatible**. The readiness revision check intentionally prevents silently serving against an unexpected schema.

## Dead outbox job

```sql
SELECT id, job_type, attempts, last_error, updated_at
FROM outbox_jobs
WHERE status = 'dead'
ORDER BY updated_at DESC;
```

Diagnose the underlying error before retrying. Do not blindly reset account-deletion jobs if the cause is a referential-integrity or deployment mismatch.

## Stuck worker

Check `running` rows whose `lease_expires_at` is in the past. A healthy worker calls lease recovery on startup and requeues them. If no worker is running, restore the Worker service or, on a hobby/free setup, wake the API service using a normal health/API request so the embedded worker resumes.

## Database incident

`/health/ready` should fail while Neon is unavailable. Do not weaken readiness to keep serving state-changing requests without the source-of-truth database.

## Secret rotation

- Rotating `TASKILLER_JWT_SECRET` invalidates existing access JWTs; refresh credentials can mint new access tokens after the deployment.
- Rotating `TASKILLER_TOKEN_HASH_SECRET` invalidates refresh/one-time/export token hashes and pseudonymization continuity. Treat this as a coordinated security event, revoke sessions and communicate the forced re-login.
- Never reuse the two secrets.

## Account/data incident

Security events are append-only except controlled retention. Use request IDs to correlate HTTP logs with user reports. Data exports can support subject-access investigations but deliberately omit authentication secrets.
