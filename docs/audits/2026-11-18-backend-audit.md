# Backend Audit — 2026-11-18

This is the original audit record. Subsequent owner clarification and implemented changes are tracked in [the remediation record](2026-11-18-backend-hardening.md): the deployment is entirely no-cost, five-minute external uptime checks keep Render awake, and the FastAPI transition preceded real users.

## Scope and conclusion

Reviewed the current backend tree at `c2382942658dbc67f07582d2aeeba3102b3d4feb`, including API/security, domain services, PostgreSQL migrations, outbox processing, exports/deletion, dependencies, CI, Docker, and the Render deployment blueprint. Vercel was considered only as the browser client's origin; frontend code was not changed or tested.

The normal product path works, but the passing checks do not establish production readiness. The highest priorities are schema parity, deletion correctness, worker liveness, and authentication abuse prevention. In particular, a fresh database created from committed Django migrations is materially different from a database that retained legacy PostgreSQL constraints and triggers.

No production database, Render account, deployed service, Mailjet delivery, or Vercel deployment was accessed. Local `.env` contents were not inspected. Application checks explicitly selected a disposable PostgreSQL 18 cluster on `127.0.0.1:55432`. No application fixes were made. Existing untracked contributor/context documentation was preserved.

## Executed validation

| Check | Result |
| --- | --- |
| Python compileall, active source/tests/scripts/manage.py | Pass |
| Ruff lint and format check | Pass; 108 files formatted |
| Pyright | Pass; configured subset only, not all API/ORM/worker code |
| Django system check | Pass |
| Fresh PostgreSQL migration/adoption script | Pass |
| `makemigrations --check --dry-run` | Pass; no drift from the incomplete model declarations |
| pytest with coverage | 35 passed; 40.87% statement coverage (2,173/5,317 statements) |
| Release/cutover contract | Pass; 54 API operations, 42 canonical paths |
| Phase 10 legacy-import audit | Pass |
| Phase 9 database baseline audit | Pass |
| Phase 9 production-shaped smoke | Pass |
| Phase 3 auth, Phase 4 work, Phase 5 focus, Phase 6 execution smokes | Pass against disposable database |
| Original Phase 7 analytics/privacy smoke | Fail: unescaped timezone `+` in query string becomes a space |
| Temporary Phase 7 copy using `urlencode` | Pass, including export processing and retention scheduling |
| Dependency vulnerability audit | Fail: three distinct advisories across certifi and dnspython; scanner duplicated one advisory |
| Docker build/image execution | Not run: installed Docker client cannot connect to its stopped engine |
| Django production-mode `check --deploy`, synthetic secret | Two warnings: Django-native HSTS setting and SSL redirect; custom middleware/proxy behavior must be considered before treating these as vulnerabilities |

WhiteNoise warned that local `staticfiles/` was absent. This is expected before collectstatic and is not evidence that the production image lacks assets: its Dockerfile runs collectstatic. An initial contract check started before the disposable database was listening timed out; the explicit rerun after migration passed.

## High-priority findings

### B01 — High: fresh migrations omit essential uniqueness and integrity protections

**Evidence:** `src/taskiller/django_domain/models.py:36`, `:182`, `:358`; `src/taskiller/django_domain/migrations/0001_existing_schema_baseline.py:13`; `src/taskiller/django_api/auth_service.py:49`; `src/taskiller/django_api/execution_service.py:175`.

Fresh PostgreSQL introspection showed only the primary-key index on `users`, no owner/open-state unique index on `execution_sessions`, and no owner/slug uniqueness on `work_types`. Registering the identical email twice succeeded. Two API session starts with distinct idempotency keys both returned 201, leaving two running sessions for the same owner. The session service catches `IntegrityError` to enforce exclusivity but neither checks for an existing open session nor installs the necessary constraint. Concurrent custom Work Type creation also has only a check-then-insert guard.

**Impact:** duplicate identities, ambiguous login/reset targeting, multiple active timers, and behavior that changes depending on how the database was provisioned. The fresh baseline also lacks the legacy database trigger/check infrastructure advertised in security documentation.

**Action:** inventory the actual hosted schema and legacy invariants; add explicit Django migrations for missing uniqueness, checks, indexes, trigger behavior, and deletion actions. Clean existing duplicates before enforcing uniqueness. Make fresh and adopted database schemas equivalent and test both. Add an explicit open-session conflict check under the existing owner lock.

**Deployment qualification:** reproduced on a fresh local database. An adopted hosted database may retain these protections; its catalog was not inspected.

### B02 — High: account deletion fails against the fresh Django schema

**Evidence:** `src/taskiller/django_operations/worker_service.py:185`; `src/taskiller/django_domain/models.py:65`, `:90`.

The worker deletes execution sessions/work items and then the user, relying on database cascades. Model relations use `DO_NOTHING`; fresh migrations do not create the required cascades. Processing a real deletion job for a registered local account raised `IntegrityError` on `auth_sessions_user_id_...`; the user remained stored. Preferences and other references can also block deletion. Scheduling already disables the account, so exhausted retries leave an inaccessible account with retained data.

**Action:** implement verified cascades or explicit dependent deletion in the correct order, preserving intended tombstones. Test full deletion with preferences, tokens, sessions, plans, events, exports, and custom types on both schema histories.

### B03 — High: dead embedded worker is not supervised

**Evidence:** `scripts/run_django_production.py:72`; `src/taskiller/django_operations/management/commands/taskiller_worker.py:33`; `src/taskiller/django_project/health.py:39`.

The parent waits only on the API. Worker startup and `claim_job()` database operations sit outside the job exception handler; database failures can terminate it. The API remains running and readiness can return healthy after recovery, with exports/deletion/retention stopped until restart.

**Action:** supervise both children, restart or exit when the worker fails, reconnect safely after database errors, and monitor worker heartbeat and oldest due-job age.

### B04 — High: recently claimed jobs can remain stuck after restart

**Evidence:** `src/taskiller/django_operations/management/commands/taskiller_worker.py:33`; `src/taskiller/django_operations/worker_service.py:58`.

Expired leases are recovered only at startup. If a replacement worker starts before the previous 60-second lease expires, recovery skips it and subsequent polling never revisits running rows. A controlled-clock local probe confirmed that the row remained `running`, owned by the dead worker, after expiry and repeated claims. Recovery also does not apply the exhausted-attempts policy.

**Action:** periodically recover expired leases and mark exhausted jobs terminal with the corresponding export/deletion state update.

### B05 — High, conditional on the configured Free plan: deadline-sensitive work stops while Render sleeps

**Evidence:** `render.yaml:5`, `:24`; embedded worker topology. Render Free web services spin down after 15 minutes without inbound traffic. Local database polling does not wake or keep such a service available. A deletion scheduled for seven days later, or retention cleanup, may wait indefinitely for another inbound request. This is a topology limitation rather than a reproduced hosted outage. [Render Free documentation](https://render.com/docs/free).

**Action:** use always-on worker compute or an independent scheduler for due work. If retaining Free hosting, document best-effort execution deadlines and externally monitor overdue jobs. Confirm the actual Render service plan; the audit saw only the committed blueprint.

## Other actionable findings

### B06 — Medium: login CSRF with cross-site refresh cookies

**Evidence:** `src/taskiller/django_api/views.py:77`, `:132`; `src/taskiller/django_api/middleware.py:44`; `render.yaml` refresh-cookie settings.

An untrusted-origin form POST reached login and returned 200 with a refresh cookie in an isolated check; the local database-backed probe also accepted an untrusted origin. CORS does not reject the operation, and DRF's auth views do not gain CSRF enforcement merely from global Django middleware. With the deployed `SameSite=None; Secure` configuration, a browser that accepts the cookie can be switched to an attacker-owned account.

**Action:** enforce trusted Origin/CSRF policy on cookie-setting and cookie-authenticated auth operations, including register/refresh, with a deliberate policy for native clients or requests lacking Origin. Browser cookie acceptance and live exploitation were not tested.

### B07 — Medium: invalid reset tokens trigger unthrottled Argon2 hashing

**Evidence:** `src/taskiller/django_api/auth_service.py:349`; `src/taskiller/django_api/views.py:342`.

Password reset hashes the proposed password before looking up the token. The public confirmation endpoint has no rate limit. Invalid tokens therefore consume expensive CPU/memory. An isolated mock confirmed hashing before rejection.

**Action:** reject invalid tokens before hashing, rate-limit the endpoint, and revalidate under lock before committing.

### B08 — Medium: registration limit is bypassed by changing email

**Evidence:** `src/taskiller/django_api/views.py:113`; `src/taskiller/django_api/security.py:41`.

The subject is `IP|email`, so every new email receives a fresh registration budget. This does not bound account creation/password hashing per source IP. Proxy spoofing is unnecessary for this bypass.

**Action:** add an independent trusted-IP budget before expensive work, retaining email-specific protection where useful. Verify Render's forwarded-header sanitization before relying on the leftmost forwarded address.

### B09 — Medium: verification email can be sent repeatedly without cooldown

**Evidence:** `src/taskiller/django_api/views.py:285`; `src/taskiller/django_api/auth_service.py:244`.

Registration immediately grants credentials for an unverified address. Repeated verification requests replace tokens and call the provider without a per-user/recipient throttle, enabling mailbox flooding and quota exhaustion.

**Action:** enforce delivery cooldowns and user/recipient budgets before token invalidation or provider calls. No real emails were sent during this audit.

### B10 — Medium: worker effects and acknowledgement are not atomic or fenced

**Evidence:** `src/taskiller/django_operations/worker_service.py:243`, `:268`, `:292`.

Processing commits before separate success acknowledgement. A crash after retention schedules its successor but before acknowledgement allows replay to create duplicate successor chains. Processing/finish/fail accepts a job ID without validating a claim generation or current owner.

**Action:** atomically commit database effects and acknowledgement, fence claims, and make retention successor creation idempotent.

### B11 — Medium: terminal retention failure removes the future schedule

**Evidence:** `src/taskiller/django_operations/worker_service.py:268`, `:307`; worker startup `:34`.

The next retention job is created only after successful cleanup. Once the current job becomes dead, no subsequent schedule is ensured until worker restart.

**Action:** maintain scheduling independently of cleanup success, periodically ensure a future job exists, and alert on terminal cleanup failures.

### B12 — Medium: export reads do not form a consistent snapshot

**Evidence:** `src/taskiller/django_operations/worker_service.py:126`.

Separate queries under default READ COMMITTED can collect sessions before a concurrent insert and events afterward, placing an event in an export without its session. Similar inconsistencies affect work items and plans. This is a source-established concurrency scenario, not a stress-test reproduction.

**Action:** collect related data under a consistent snapshot, then serialize/compress outside the read transaction where practical.

### B13 — Medium: concurrent reorders have conflicting lock order

**Evidence:** `src/taskiller/django_api/work_service.py:623`, `:631`, `:641`.

Each request locks its selected sibling before the shared parent/owner namespace, then locks all siblings. Two requests selecting different siblings can produce a cycle: one holds the namespace and waits for the other's row, while the other holds that row and waits for the namespace. PostgreSQL aborts one; no domain-level recovery is provided.

**Action:** establish a common lock order across reorder/move/create/execution: namespace before sibling rows, then revalidate membership and version. Source-established lock cycle; no concurrent load test was run.

### B14 — Medium: deleting a referenced Work Type can return 500

**Evidence:** `src/taskiller/django_api/work_service.py:273`; `src/taskiller/django_domain/models.py:228`.

The service directly deletes a custom type referenced by a Work Item. `DO_NOTHING` plus fresh-schema foreign keys blocks commit instead of clearing references or returning a stable conflict. Soft-deleted referencing items can also block it.

**Action:** transactionally clear affected references with appropriate version updates, or intentionally reject with a documented 409. Verify adopted-schema behavior separately.

### B15 — Medium: session start does not revalidate linked Sprint chores

**Evidence:** `src/taskiller/django_api/focus_service.py:657`; `src/taskiller/django_api/execution_service.py:228`, `:269`.

A plan can link a Sprint child that is subsequently moved or soft-deleted. Start checks the plan target but does not revalidate those links; execution can attribute work to a stale item while later completion rejects it.

**Action:** validate linked ownership, live state, and current target relationship at start with coordinated locking.

### B16 — Medium: malformed pagination cursor returns a server error

**Evidence:** `src/taskiller/django_api/execution_service.py:969`.

`W10=` decodes to `[]`; indexing raises uncaught `IndexError`. Reproduced by calling the actual decoder. Valid JSON objects can similarly produce uncaught key access errors.

**Action:** validate decoded container, length, and scalar types before indexing and consistently return `422 invalid_cursor`.

### B17 — Medium: portable import's mandatory header is missing from its contract

**Evidence:** `src/taskiller/django_api/portable_views.py:19`, `:26`; `openapi/current.json:6178`.

Runtime requires `Idempotency-Key`, but the operation does not declare it. Contract-following clients can receive 422 for otherwise valid imports. The passing release check compares paths, operation IDs, and security; it does not establish request/response schema parity.

**Action:** declare the required header and bounds in metadata and the canonical document; add request/response contract validation, then coordinate generated client artifacts.

### B18 — Medium: locked runtime dependencies have published advisories

**Evidence:** `uv.lock:90`, `:217`; pip-audit against installed site-packages matched these locked versions.

- `certifi 2026.7.22`: `PYSEC-2026-4320` / `GHSA-6q48-6c7w-9gw2`, affected trust roots. Auditor lists a fix in 2026.10.18 and describes subsequent restoration in 2026.10.19. Rebuild with a current fixed trust bundle. [Maintainer advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
- `dnspython 2.8.0`: `CVE-2026-114605` / `GHSA-45c3-73f7-pv4m`, DNS name-decompression CPU use; fixed in 2.9.0. Also `CVE-2026-128089` / `GHSA-vvf4-9x63-8xvv`, WKS zone parsing resource exhaustion; auditor lists 2.9.2. These advisories do not establish that the API exposes those parsing paths. [Maintainer DNS advisory](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m).

**Action:** update compatible locked dependencies, rerun validation, rebuild the image, and add dependency auditing to CI. Scanner reported four entries, but one certifi advisory was duplicated: three distinct advisories, not four distinct vulnerabilities.

### B19 — Medium, local development: PostgreSQL 18 volume targets the old directory

**Evidence:** `compose.yaml:16` mounts the named volume at `/var/lib/postgresql/data` with `postgres:18-alpine`. PostgreSQL 18's official image changed PGDATA and its recommended mount to `/var/lib/postgresql`. The named mount does not protect the intended current data directory and can cause initialization/persistence problems. Docker execution was unavailable, so exact container behavior was not reproduced. [Official image documentation](https://hub.docker.com/_/postgres).

**Action:** use the PostgreSQL 18 volume layout and a deliberate migration of any existing local data. Do not delete or replace volumes before backup and verification.

### B20 — Medium: email replacement is not durable across provider/process failures

**Evidence:** `src/taskiller/django_api/auth_service.py:244`, `:311`; `src/taskiller/auth/email.py:227`, `:237`.

Old one-time links are consumed and replacement tokens committed before email delivery, without a durable retry. Provider failure leaves the user with invalidated old links and no delivered replacement. Mailjet response handling also treats missing message status or an empty response as success.

**Action:** persist delivery work atomically with token issuance, retry the same token, define invalidation timing, and require explicit provider acceptance.

## Validation and operational gaps

- The 35-test suite gives 40.87% statement coverage, with authentication service around 21%, execution/work services around 19%, and worker around 16%. These are measured test-suite figures; smoke scripts were run separately and are not included in that percentage. Add fresh-schema constraint tests, deletion/retention/restart tests, multi-user authorization cases, concurrency tests, and malformed-input tests.
- `scripts/django_phase7_smoke.py:40` interpolates ISO timestamps directly into a query string. Using `urlencode` in a temporary copy fixed its failure; the original remains unchanged. CI runs the narrower Phase 9 smoke, not this broader privacy smoke.
- Migration drift and the baseline audit cannot detect missing intended constraints when both model declarations and migration state omit them. Check actual database catalogs and invariants, including adopted versus fresh databases.
- Startup migration execution has no advisory lock in `scripts/django_cutover_migrate.py`. Concurrent overlapping starts/migrators can race. Serialize migrations or use a dedicated controlled migration step; assess the actual Render rollout topology first.
- `docs/PRODUCTION.md` references removed `apply_django_phase8.py` and `taskiller.main:app`; root `VALIDATION.md` describes old FastAPI/Alembic results. Update these before relying on them for rollback or release decisions.
- `database_pool_*` settings remain exposed in configuration but are not wired to Django's database backend. Current `CONN_MAX_AGE=60` deserves ASGI/Neon connection-budget validation. No load test or production connection measurement was run.
- The custom JSON logging configurator has no call site in active source/scripts, and middleware stores duration without emitting a request-completion log. Verify available Render/Uvicorn logs and ensure failed jobs/queue lag are observable.

## Hosted checks still required

Inspect Render's actual plan, release SHA, environment settings, readiness, worker liveness, and startup logs; inspect the hosted PostgreSQL constraint/trigger/index catalog and backup/restore procedure. Confirm CORS permits only intended Vercel/custom origins and cookies have the configured attributes. Test refresh persistence in browsers that restrict third-party cookies if using unrelated `onrender.com` and `vercel.app` sites. Verify HTTPS redirects at the proxy; custom production middleware already supplies HSTS, so Django's HSTS warning alone is not a missing-header finding. Validate proxy header sanitization before drawing conclusions about IP spoofing.

No load, penetration, live browser-cookie, disaster-recovery, container-runtime, or legacy-schema-adoption test is claimed.

## Recommended order

1. Inventory hosted schema; repair schema parity and account deletion, with regression tests for both provisioning histories.
2. Repair worker supervision, periodic lease recovery, retention scheduling, and claim/acknowledgement semantics; resolve the Free-plan deadline limitation.
3. Add auth Origin/CSRF enforcement and abuse budgets; avoid invalid-token hashing and make email delivery durable.
4. Update vulnerable dependencies and rebuild; fix malformed cursors, stale links, Work Type deletion, reorder locking, and portable contract metadata.
5. Expand CI beyond happy-path smoke and refresh deployment/rollback documentation; complete hosted and container verification.
