# Phase 8 Cutover Runbook

1. Apply the cumulative Phase 8 installer.
2. `uv lock && uv sync --dev`.
3. Generate the one-time domain migration:
   `PYTHONPATH=src uv run python scripts/prepare_django_baseline.py`
4. Review the generated migration. It should be an initial migration describing the existing
   Taskiller tables; do not hand-add destructive operations.
5. Commit the migration.
6. Against a disposable database:
   - `uv run alembic upgrade head` (legacy bootstrap only)
   - `PYTHONPATH=src uv run python scripts/django_cutover_migrate.py`
   - run all Phase 2–8 checks
7. Set `TASKILLER_DJANGO_SECRET_KEY` on Render.
8. Deploy.
9. Verify:
   - `/health/live`
   - `/health/ready`
   - `/openapi.json`
   - login/refresh
   - Work create/edit
   - Focus recommendation
   - session start/event/finish
   - analytics
   - export job
10. Run the frontend Playwright suite against the Render Django API.
11. Keep the FastAPI rollback entrypoint until the production observation window is complete.

After cutover, Django migrations are the only allowed schema-change mechanism.
