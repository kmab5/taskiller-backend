# Phase 10 — Final Django Transfer

Phase 10 completes the backend transfer.

The supported backend stack is now exclusively:

- Django 5.2 LTS
- Django REST Framework
- Django ORM
- Django migrations
- PostgreSQL / Neon
- Django management-command outbox worker
- Uvicorn ASGI
- Mailjet HTTPS API

FastAPI, SQLAlchemy and Alembic are removed from the installable production backend and default
dependency set.

Historical implementation files are moved to `legacy_backend/` for source reference only. They are
not packaged, imported, tested or supported as a runtime.

## Final validation

```bash
uv lock
uv sync --dev
PYTHONPATH=src uv run python manage.py check
PYTHONPATH=src uv run python manage.py makemigrations --check --dry-run
PYTHONPATH=src uv run python manage.py migrate
PYTHONPATH=src uv run python scripts/django_phase10_final_audit.py
PYTHONPATH=src uv run python scripts/django_phase9_production_smoke.py
uv run pytest
docker build -t taskiller-backend:django-final .
```

Then run the real-backend frontend test:

```bash
TASKILLER_DJANGO_API_URL=http://127.0.0.1:8000 npm run test:e2e:django
```

After Phase 10 there is no additional migration phase planned. Future work is normal product
development on the Django backend.
