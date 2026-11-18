# Production Runbook

## Release

1. Merge only a green `main` build.
2. Confirm the committed `openapi/current.json` changed intentionally.
3. Render builds the Dockerfile from the selected Git SHA.
4. Container startup runs `scripts/django_cutover_migrate.py`; transaction-scoped advisory locking serializes migration launchers.
5. Uvicorn starts only after migration succeeds.
6. Render uses `/health/ready` for deployment health checks.
7. Confirm `/health/version` shows the intended SHA.
8. Run `python scripts/load_smoke.py --base-url https://<api-host>` from an operator machine.

## Migration failure

Do not bypass readiness. Inspect Render migration/database logs, correct the condition, and redeploy. New constraints reject conflicting records rather than removing them automatically.

## Rollback

Application rollback and schema rollback are separate decisions. Prefer forward-fixing a migrated database. Use only Django migrations; archived FastAPI/Alembic entrypoints are not a rollback procedure.

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

Check `running` rows whose `lease_expires_at` is in the past. Recovery runs every 15 seconds and marks exhausted attempts dead. The supervisor exits if either child dies. Restore the Render service and confirm the external five-minute uptime check is active. A live but stalled worker requires a restart and investigation.

## Database incident

`/health/ready` should fail while Neon is unavailable. Do not weaken readiness to keep serving state-changing requests without the source-of-truth database.

## Secret rotation

- Rotating `TASKILLER_JWT_SECRET` invalidates existing access JWTs; refresh credentials can mint new access tokens after the deployment.
- Rotating `TASKILLER_TOKEN_HASH_SECRET` invalidates refresh/one-time/export token hashes, pending email reconstruction, and pseudonymization continuity. Treat this as a coordinated security event, revoke sessions and communicate the forced re-login.
- Never reuse the two secrets.

## Account/data incident

Security events are append-only except controlled retention. Ask for response request IDs during client investigations; completion logs currently record path/status/duration. Exports deliberately omit authentication secrets.
