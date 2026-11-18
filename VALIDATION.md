# Django Backend Validation

Validated locally on 2026-11-18 using Python 3.14.6 and disposable PostgreSQL 18. This supersedes the former FastAPI/Alembic validation record. See `docs/audits/2026-11-18-backend-hardening.md` for the complete remediation map.

## Results

- Full pytest suite: **150 passed** with integration tests enabled.
- Statement coverage: **56.42%**, up from the audit baseline of 40.87%. Smoke scripts are measured separately, not included in that figure.
- Ruff lint and format: pass; 122 Python files formatted.
- Pyright: pass, covering only the configured framework-neutral subset.
- Django system check and migration drift: pass.
- Fresh database startup migrations: pass, including migrations 0003–0005 and transaction-scoped startup locking.
- Actual PostgreSQL constraints/indexes/ownership/history trigger audit: pass.
- Auth, Work, Focus, Execution, Analytics/privacy/worker, and production-shaped smoke scripts: pass.
- Release/cutover contract: pass, 54 API operations and 42 canonical paths.
- Phase 10 legacy-import audit and Python compilation: pass.
- Frozen lock consistency and hashed runtime dependency audit: pass; no known vulnerabilities reported.
- collectstatic: pass, 154 files copied and 444 post-processed.

The native production launcher was also exercised over local HTTP: readiness 200, trusted Vercel-origin preflight 204, untrusted-origin login 403, and 30 concurrent health requests with zero failures. Deliberately stopping its API child caused supervisor exit and worker cleanup. PostgreSQL regression tests cover complete account deletion, failed/expired claim recovery, stale acknowledgements, transactional rollback, repeatable-read snapshots, concurrent sibling reorder, and durable email delivery through a stubbed provider.

## Reproduction

Use an explicitly disposable local database. In PowerShell:

```powershell
$env:PYTHONPATH = 'src'
$env:TASKILLER_ENV = 'test'
$env:TASKILLER_DATABASE_URL = 'postgresql://taskiller:taskiller@localhost:5432/taskiller_test'
$env:TASKILLER_TEST_DATABASE_URL = $env:TASKILLER_DATABASE_URL
$env:TASKILLER_EMAIL_DELIVERY_MODE = 'safe_log'
uv sync --dev --frozen
uv run python scripts/django_cutover_migrate.py
uv run pytest --cov=taskiller --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python scripts/django_phase9_baseline_audit.py
uv run python scripts/release_check.py
```

CI runs the domain smoke scripts and container checks as well. Integration-marked tests skip when no explicit test URL is supplied and refuse a nonlocal or mismatched database configuration.

## Limits

Docker's client is installed but its engine is stopped; a local image build/runtime is not claimed. The native launcher and static collection checks do not substitute for container verification. No hosted database, Render account configuration, real Mailjet delivery, Vercel frontend/browser tests, historical FastAPI adoption, or backup restore was exercised. The existing five-minute external uptime monitor remains owner-managed. No paid service was added.
