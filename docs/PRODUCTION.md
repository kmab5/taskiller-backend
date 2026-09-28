# Production Deployment — Koyeb + Neon

This is the supported v1 deployment target.

## Topology

```text
Internet
   |
Koyeb edge/TLS
   |
Taskiller Web Service  ---->  Neon pooled PostgreSQL
   |
   +---- optional embedded outbox worker (free/hobby only)

Paid/production:
Taskiller Worker Service ---> same Neon database
```

Use **Frankfurt (`fra`)** when serving primarily Türkiye/Europe unless measurements justify another region. Keep Neon in a nearby European region as well.

## Neon

Use the **pooled** Neon connection string (`-pooler` in the endpoint host). Neon currently fronts pooled connections with PgBouncer in transaction mode. Taskiller also keeps a deliberately small client-side SQLAlchemy pool; defaults are `pool_size=5`, `max_overflow=5` and are configurable.

Set the complete SQLAlchemy/psycopg URL as `TASKILLER_DATABASE_URL`, preserving Neon's TLS parameters.

## Koyeb Web Service

Deploy `kmab5/taskiller-backend` from GitHub using the repository `Dockerfile`.

- Service type: Web
- Port: `8000` (Koyeb also provides `PORT`; the container honors it)
- Public route: `/`
- Health check: HTTP `/health/ready`
- Region: Frankfurt for the initial deployment
- Build method: Dockerfile

Required production environment values include:

```text
TASKILLER_ENV=production
TASKILLER_DATABASE_URL=<Neon pooled SQLAlchemy/psycopg URL>
TASKILLER_JWT_SECRET=<independent >=32-byte secret>
TASKILLER_TOKEN_HASH_SECRET=<different independent >=32-byte secret>
TASKILLER_EMAIL_DELIVERY_MODE=smtp
TASKILLER_SMTP_HOST=<provider SMTP host>
TASKILLER_SMTP_PORT=587
TASKILLER_SMTP_USERNAME=<provider username if required>
TASKILLER_SMTP_PASSWORD=<provider password if required>
TASKILLER_SMTP_FROM_EMAIL=Taskiller <noreply@your-domain>
TASKILLER_CORS_ORIGINS=["https://<taskiller-web-host>"]
TASKILLER_ALLOWED_HOSTS=["<api-host>"]
TASKILLER_TRUST_FORWARDED_FOR=true
TASKILLER_REFRESH_COOKIE_SECURE=true
```

If the web client is hosted on a different **site** (not merely a different subdomain of the same registrable domain), the refresh cookie must use `TASKILLER_REFRESH_COOKIE_SAMESITE=none` together with `TASKILLER_REFRESH_COOKIE_SECURE=true`. Prefer same-site custom domains such as `app.example.com` + `api.example.com` when possible.

Generate each auth secret independently, e.g. `openssl rand -hex 32`. Production startup rejects non-SMTP email mode so verification/password-reset endpoints cannot silently accept work that will never be delivered.

Koyeb sets `KOYEB_GIT_SHA`, `KOYEB_GIT_BRANCH` and `KOYEB_GIT_REPOSITORY` for Git deployments. `/health/version` surfaces these values for release diagnosis.

## Worker modes

### Free/hobby Koyeb

As of 2026-09-28, Koyeb allows one Free Instance per organization, the free instance is Web-Service-only, and it scales to zero after one hour without traffic. Set:

```text
TASKILLER_EMBEDDED_WORKER_ENABLED=true
```

This is acceptable for development/hobby use but **not an SLA-quality production topology**. A sleeping free Web Service cannot wake itself merely because an outbox job becomes due; the next incoming request wakes it and background processing resumes.

### Production

Use a second Koyeb **Worker** Service from the same image/repository and set the API to:

```text
TASKILLER_EMBEDDED_WORKER_ENABLED=false
```

Override the Worker command to:

```sh
sh -c 'python scripts/migrate.py && exec python -m taskiller.operations.worker'
```

Both services may run the migration launcher because its PostgreSQL advisory lock serializes migration execution.

## Health

- `/health/live`: process liveness only.
- `/health/ready`: PostgreSQL reachable **and** Alembic revision equals the release's expected revision.
- `/health/version`: version and deployment commit metadata.

Configure Koyeb's HTTP health check against `/health/ready`, not `/health/live`, so an instance with a stale schema never receives traffic.

## Platform references

- Koyeb health checks: https://www.koyeb.com/docs/run-and-scale/health-checks
- Koyeb edge headers/TLS: https://www.koyeb.com/docs/reference/edge-network
- Koyeb free instance limits: https://www.koyeb.com/docs/reference/instances
- Koyeb Git deployment: https://www.koyeb.com/docs/build-and-deploy/deploy-with-git
- Neon PgBouncer/pooled connections: https://neon.com/blog/pgbouncer-the-one-with-prepared-statements
