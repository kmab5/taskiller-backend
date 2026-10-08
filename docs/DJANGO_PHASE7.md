# Django Migration — Phase 7 Analytics + Operations

Backend `b1de8835a1eb348a7389378297187e76c9715c51` / frontend `c49bedaf7dc33dc13403d298be092b02562def09`.

Cumulative Phase 1–7.

Analytics now loads history through Django ORM while retaining the existing proven
metric derivation/calculation implementation.

A Django-native worker now handles:

- expired lease recovery
- retention scheduling
- `FOR UPDATE SKIP LOCKED` job claims
- data export archive generation
- delayed account deletion
- retention cleanup
- retries/backoff and dead-letter terminal state

Commands:

```bash
PYTHONPATH=src uv run python manage.py taskiller_worker
PYTHONPATH=src uv run python manage.py taskiller_worker --once
```

Production remains FastAPI until the final cutover phase.
