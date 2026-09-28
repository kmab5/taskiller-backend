# Round 7 Validation

Validated on 2026-09-28 in the artifact environment.

- Source baseline: GitHub `kmab5/taskiller-backend` main commit `f3cd20c64738c4bbaa0377a4772d306ef170d9b6`.
- The reconstructed local Round-6 tree SHA exactly matched upstream: `70eb8a7f2d74e66abfc33dace9a3b6c2998d5fce`.
- `pytest -q`: **61 passed, 30 skipped**. Skips require `TASKILLER_TEST_DATABASE_URL`; three are new Round-7 PostgreSQL tests.
- `python -m compileall src tests alembic`: passed.
- PostgreSQL integration coverage added for export generation/download, deletion revocation + hard deletion, and failed-login rate limiting.
- Ruff/Pyright/PostgreSQL execution remain CI-authoritative because those tools/services are unavailable in this sandbox.
