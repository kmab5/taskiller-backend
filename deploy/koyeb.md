# Koyeb Deployment Checklist

See `docs/PRODUCTION.md` for rationale.

## API Web Service

- Git repo: `kmab5/taskiller-backend`
- branch: `main`
- builder: Dockerfile
- region: `fra`
- public HTTP port: `8000`
- route: `/`
- HTTP health check: `/health/ready`
- environment/secrets: configure all production `TASKILLER_*` values

The image default command applies advisory-locked migrations and then starts Uvicorn. Koyeb-provided `PORT` is honored.

## Worker Service (paid production)

Use the same Git/Docker image, no public port, and override the command:

```sh
sh -c 'python scripts/migrate.py && exec python -m taskiller.operations.worker'
```

Set `TASKILLER_EMBEDDED_WORKER_ENABLED=false` on the API.

## One-free-instance preview

A Koyeb Free Instance cannot be a Worker Service. For a $0 preview, set the API Web Service to `TASKILLER_EMBEDDED_WORKER_ENABLED=true`. Treat this as development/hobby deployment because free instances scale to zero and Koyeb explicitly describes them as unsuitable for production applications.
