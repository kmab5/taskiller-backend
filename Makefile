.PHONY: install dev lint format typecheck test test-integration check db-up db-down migrate openapi

install:
	uv sync --dev

dev:
	uv run uvicorn taskiller.main:app --app-dir src --reload --host 0.0.0.0 --port 8000

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

check: lint typecheck test

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head

openapi:
	PYTHONPATH=src uv run python scripts/export_openapi.py
