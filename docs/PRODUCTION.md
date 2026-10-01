# Production Deployment — Render + Neon + Vercel

Taskiller's current zero-cost deployment topology is:

```text
Browser / installed PWA
        |
        v
Vercel — taskiller-web
        |
        | HTTPS REST API
        v
Render Free — taskiller-api
        | \
        |  \ HTTPS
        |   -> Mailjet Send API v3.1
        v
Neon — PostgreSQL
```

## Render API

Deploy `kmab5/taskiller-backend` from GitHub using the repository `Dockerfile`.

- Runtime: Docker
- Plan: Free
- Branch: `main`
- Health check: `/health/ready`
- Embedded worker: enabled for the one-service free deployment

Required production environment values:

```text
TASKILLER_ENV=production
TASKILLER_DATABASE_URL=<Neon pooled SQLAlchemy/psycopg URL>
TASKILLER_JWT_SECRET=<independent strong secret>
TASKILLER_TOKEN_HASH_SECRET=<different independent strong secret>

TASKILLER_EMAIL_DELIVERY_MODE=mailjet
TASKILLER_WEB_APP_URL=https://taskiller-web.vercel.app
TASKILLER_MAILJET_API_KEY=<Mailjet public API key>
TASKILLER_MAILJET_SECRET_KEY=<Mailjet private/secret API key>
TASKILLER_MAILJET_FROM_EMAIL=<verified Mailjet sender address>
TASKILLER_MAILJET_FROM_NAME=Taskiller

TASKILLER_CORS_ORIGINS=["https://taskiller-web.vercel.app"]
TASKILLER_ALLOWED_HOSTS=["taskiller-api-ukwf.onrender.com"]
TASKILLER_TRUST_FORWARDED_FOR=true

TASKILLER_REFRESH_COOKIE_SECURE=true
TASKILLER_REFRESH_COOKIE_SAMESITE=none
TASKILLER_EMBEDDED_WORKER_ENABLED=true
```

Keep all provider keys and authentication secrets only in Render environment variables.

## Mailjet

Taskiller uses Mailjet's HTTPS Send API v3.1 rather than SMTP. The sender must be an active sender address in the Mailjet account attached to the configured API key.

The backend sends:

- email-verification links to `/verify-email?token=...`
- password-reset links to `/reset-password?token=...`

`TASKILLER_WEB_APP_URL` controls the public frontend origin used in those links.

A Gmail sender address can be activated in Mailjet without owning its domain, but Gmail's SPF/DKIM records cannot be changed by the Taskiller operator. That is acceptable for initial development and small-scale testing but can reduce deliverability compared with a future custom domain.

## Neon

Use the pooled Neon connection string (`-pooler` endpoint where applicable) as `TASKILLER_DATABASE_URL`.

## Refresh cookie

Vercel and Render are cross-site hosts, so production uses:

```text
TASKILLER_REFRESH_COOKIE_SAMESITE=none
TASKILLER_REFRESH_COOKIE_SECURE=true
```

## Embedded worker

Render Free only runs the web service. Keep:

```text
TASKILLER_EMBEDDED_WORKER_ENABLED=true
```

The embedded worker processes data exports, account deletion, and retention work while the API instance is awake.

## Health

- `/health/live` — process liveness
- `/health/ready` — PostgreSQL reachable and schema at the expected Alembic revision
- `/health/version` — build version and deployment metadata
