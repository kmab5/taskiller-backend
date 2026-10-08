.PHONY: install dev lint format format-check typecheck compile test check migrate release-check phase10-audit worker

install:
	uv sync --dev

dev:
	PYTHONPATH=src uv run python manage.py runserver 0.0.0.0:8000

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

compile:
	uv run python -m compileall -q src tests scripts manage.py

test:
	uv run pytest

migrate:
	PYTHONPATH=src uv run python manage.py migrate

worker:
	PYTHONPATH=src uv run python manage.py taskiller_worker

release-check:
	PYTHONPATH=src uv run python scripts/release_check.py

phase10-audit:
	PYTHONPATH=src uv run python scripts/django_phase10_final_audit.py
	PYTHONPATH=src uv run python scripts/django_phase9_baseline_audit.py
	PYTHONPATH=src uv run python scripts/django_phase9_production_smoke.py

check: compile lint format-check typecheck test release-check phase10-audit
