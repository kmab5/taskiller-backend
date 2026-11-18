# taskiller-backend

Client-independent backend for **Taskiller**, now fully migrated to Django.

## Production stack

- Python 3.14
- Django 5.2 LTS
- Django REST Framework
- Django ORM
- Django migrations
- PostgreSQL / Neon
- Uvicorn ASGI
- PostgreSQL outbox worker implemented as a Django management command
- Mailjet HTTPS API
- PyJWT
- pwdlib / Argon2id
- pytest
- Ruff
- Pyright
- uv
- Docker
- Render

The public `/api/v1` contract is preserved from the original v1 API. `openapi/current.json`
remains the canonical fully typed client contract and is served by Django at `/openapi.json`.

## Local setup

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --dev
PYTHONPATH=src uv run python manage.py migrate
PYTHONPATH=src uv run python manage.py runserver 0.0.0.0:8000
```

Then open:

- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`
- `http://localhost:8000/admin/`
- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`

## Background worker

```bash
PYTHONPATH=src uv run python manage.py taskiller_worker
```

Render's one-service free deployment can run the worker alongside ASGI through
`scripts/run_django_production.py`.

## Schema changes

Django migrations are the only supported schema-change mechanism:

```bash
PYTHONPATH=src uv run python manage.py makemigrations
PYTHONPATH=src uv run python manage.py migrate
```

Do not create new Alembic migrations.

## Validation

```bash
make check
```

PostgreSQL integration tests require an explicit disposable local test database.
In PowerShell, set both URLs to the same database before running pytest:

```powershell
$env:TASKILLER_ENV = 'test'
$env:TASKILLER_DATABASE_URL = 'postgresql://taskiller:taskiller@localhost:5432/taskiller_test'
$env:TASKILLER_TEST_DATABASE_URL = $env:TASKILLER_DATABASE_URL
uv run pytest
```

CI also runs the auth, work, focus, execution, and privacy/worker smoke scripts.
See `docs/PRODUCTION.md` for the no-cost Render setup and five-minute uptime checks.

For the full client/server integration test, also run the web repository's:

```bash
TASKILLER_DJANGO_API_URL=http://127.0.0.1:8000 npm run test:e2e:django
```

## Legacy archive

The old FastAPI/SQLAlchemy/Alembic implementation is retained under `legacy_backend/` only as
historical source material. It is not installed, imported, tested, deployed or supported as a
runtime.

See `docs/DJANGO_PHASE10.md`.
