# Round 6 Validation

Validated on 2026-09-28 in the artifact environment.

## Passed locally

- full `pytest -q`: **58 passed, 27 skipped**
  - the 27 skipped tests require `TASKILLER_TEST_DATABASE_URL`
  - three of those are new Round 6 PostgreSQL analytics/personalization tests
- `python -m compileall src tests alembic`: passed
- SQLAlchemy mapper configuration: passed, **15 mapped tables**
- FastAPI application/OpenAPI construction: passed
- generated OpenAPI: **3.1.0**, API version **0.6.0**, **37 paths / 51 operations**
- generated local OpenAPI `$ref` resolution: **177 references, 0 broken**
- OpenAPI export written to `openapi/current.json`
- Alembic offline `upgrade head --sql`: passed through revision `20260928_0005`
- Alembic offline downgrade `20260928_0005:base --sql`: passed
- source/test/migration 100-character line-length scan: passed
- simple AST unused-import scan: no non-`__future__` candidates
- `git diff --check`: passed

## Round 6 regression coverage

Unit/contract coverage verifies deterministic Session interval reconstruction, pause exclusion,
WorkItem attribution, query-window clipping, completion inference, open-Session handling,
analytics OpenAPI paths, offset-aware ranges, public week-start numbering, conservative
personalization thresholds, and history-informed focus-block generation.

PostgreSQL integration coverage is included for:

- exact user/Work-Type/WorkItem/time-series/focus-pattern values from authoritative Session Events;
- history-informed recommendation provenance after the minimum supported personal-history sample;
- database rejection of historical Work-context snapshot mutation.

Existing authentication, Work, Focus and Execution suites remain included.

## Analytics invariants added

Round 6 adds immutable `execution_sessions.work_context_snapshot_json`. New Sessions snapshot
the target and linked WorkItems' Work Type, estimate, planned start and ancestry. The migration
backfills existing Sessions with the best context available at migration time, including linked
Sprint Chores, and the PostgreSQL execution-session trigger prevents later mutation. Analytics
therefore do not reinterpret old Sessions using a task's current parent, Work Type, estimate or
planned-start value.

Personalization is deliberately gated. A Work Type needs at least five completed Sessions,
at least five qualifying uninterrupted-work intervals, and supportive review evidence; when
review evidence is sparse, the Session threshold rises to eight. The engine records the exact
sample information and labels the signal descriptive rather than causal.

## Environment limitations

This artifact runtime uses Python 3.13 while the project target is Python 3.14. A PostgreSQL
server, Ruff and Pyright binaries are not installed. Direct package installation is unavailable
from the container, so those missing tools could not be added here.

Therefore PostgreSQL integration tests, Ruff and Pyright are **not claimed as locally executed**.
CI remains authoritative: `.github/workflows/ci.yml` uses Python 3.14, installs declared
dependencies, runs Ruff formatting/lint and Pyright, provisions PostgreSQL 18, applies all
migrations, runs the complete suite, exports OpenAPI and builds the container.
