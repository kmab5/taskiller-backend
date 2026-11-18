# Production Deployment

## No-cost topology

The SvelteKit frontend runs on Vercel; Django ASGI and its embedded PostgreSQL outbox worker share one Render Free web service. Neon stores application data and temporary exports. Authentication mail uses Mailjet's HTTPS API. No Redis, paid worker, or additional hosted component is required.

An externally configured uptime monitor sends a normal HTTP request every five minutes. Keep that monitor enabled and alert on failures. `/health/live` is a cheap process check; `/health/ready` also checks PostgreSQL and migrations. Render's deployment health check is `/health/ready`. The external monitor is not managed by this repository.

The checks address normal idle sleep, but restarts, exhausted provider allowances, monitor outages, and provider incidents can interrupt processing. Due jobs resume after recovery; no-cost hosting does not provide an exact execution-time guarantee. See [Render's Free documentation](https://render.com/docs/free).

## Runtime and secrets

The Docker entrypoint is `python scripts/run_django_production.py`. It serializes and applies committed Django migrations, starts the embedded worker when enabled, starts Uvicorn, and terminates both children if either exits. The worker retries database outages and periodically recovers abandoned jobs.

Keep these in Render environment settings:

- `TASKILLER_ENV=production`, `TASKILLER_EMBEDDED_WORKER_ENABLED=true`.
- Neon `TASKILLER_DATABASE_URL`, including required TLS options. Django disables per-thread persistent ASGI connections; Neon's pooler handles upstream pooling.
- Independent strong `TASKILLER_DJANGO_SECRET_KEY`, `TASKILLER_JWT_SECRET`, and `TASKILLER_TOKEN_HASH_SECRET`.
- `TASKILLER_EMAIL_DELIVERY_MODE=mailjet`, Mailjet key/secret/verified sender, and `TASKILLER_WEB_APP_URL` pointing at the frontend.
- JSON arrays for `TASKILLER_ALLOWED_HOSTS` and `TASKILLER_CORS_ORIGINS`; use the exact intended hosts and browser origins. Explicitly add any preview origin that needs login; do not use wildcard origins.
- For unrelated Render/Vercel domains, `TASKILLER_REFRESH_COOKIE_SECURE=true` and `TASKILLER_REFRESH_COOKIE_SAMESITE=none`. Browser third-party-cookie restrictions still require browser verification.

Trust forwarded addresses only behind the intended proxy. Keep credentials out of `.env.example`, Git, and logs. Rotate the token-HMAC secret deliberately: pending email jobs reconstruct tokens from it, so rotation invalidates them along with other opaque credentials.

## Database changes

Use committed Django migrations only. New databases include uniqueness constraints, ownership/hierarchy guards, append-only history, and queue indexes. Startup uses a transaction-scoped PostgreSQL advisory lock, compatible with transaction pooling. Current migrations are transactional; review this runner before introducing nontransactional DDL.

The FastAPI-to-Django transition happened before real users existed. Legacy adoption helpers remain historical compatibility paths. Do not regenerate the baseline or run an archived FastAPI entrypoint for normal deployment. New constraints refuse conflicting development records instead of deleting data silently. Resolve startup constraint failures deliberately.

## API and release checks

`/openapi.json` serves `openapi/current.json`. Review contract changes and coordinate frontend snapshot/type regeneration when needed. Authentication mail responses indicate queue acceptance, not confirmed inbox delivery.

CI validates fresh migrations, actual database indexes/triggers, API contracts, domain/worker regressions, dependency advisories, and the production image. Follow `docs/RUNBOOK.md` for releases and incidents. Local Compose now uses PostgreSQL 18's `/var/lib/postgresql` volume layout; back up and intentionally move any existing local data before recreating a container.

## Rollback

Redeploy a compatible earlier Django commit for a code rollback. Prefer a forward fix after schema changes. Do not run Alembic downgrades or restore FastAPI: the archive is not installed. Review backups and dependent data before an explicitly planned Django migration rollback.
