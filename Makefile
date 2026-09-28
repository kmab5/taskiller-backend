.PHONY: install dev lint format format-check typecheck compile test test-integration check db-up db-down migrate openapi release-check load-smoke

install:
	uv sync --dev

dev:
	uv run uvicorn taskiller.main:app --app-dir src --reload --host 0.0.0.0 --port 8000

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

compile:
	uv run python -m compileall -q src tests scripts alembic

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

check: compile lint format-check typecheck test release-check

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

migrate:
	PYTHONPATH=src uv run python scripts/migrate.py

openapi:
	PYTHONPATH=src uv run python scripts/export_openapi.py

release-check: openapi
	PYTHONPATH=src uv run python scripts/release_check.py

load-smoke:
	PYTHONPATH=src uv run python scripts/load_smoke.py --base-url http://localhost:8000
