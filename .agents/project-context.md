# Taskiller Cross-Repository Context

Verified against local documentation, configuration, and selected source files on 2026-11-18. These notes persist project context for future agents; recheck the source before relying on version-sensitive details. No application tests were run to produce these notes.

## Repository Map and Source Authority

Owner-confirmed deployment constraint (2026-11-18): keep the implementation entirely no-cost. External five-minute uptime checks keep Render Free awake. Django replaced FastAPI before real users existed; prioritize the current schema over elaborate legacy adoption guarantees. See `docs/PRODUCTION.md` and `docs/audits/2026-11-18-backend-hardening.md` for current operations and audit remediation.

| Location | Role | Start here |
| --- | --- | --- |
| `D:/Code/taskiller-backend` | Active Python 3.14 / Django 5.2 / DRF API and PostgreSQL worker | `AGENTS.md`, `README.md`, `src/taskiller/`, `docs/DJANGO_PHASE10.md` |
| `D:/Code/taskiller-web` | Svelte 5 / SvelteKit 2 / TypeScript client, Tailwind 4, TanStack Svelte Query, openapi-fetch | `AGENTS.md`, `package.json`, `src/lib/api/`, `src/routes/` |
| `D:/Code/taskiller` | Planning package, English/Turkish PRDs, domain specifications, research, examples, brand kit | `README.md`, `MANIFEST.md`, `docs/`, `brand-kit/START_HERE.md` |

The planning package explains product intent, not the current runtime stack. Its Node.js/NestJS/Prisma direction predates the Django implementation. Its `api/openapi.yaml` and `db/schema.sql` are planning references; use backend `openapi/current.json` and Django models/migrations for the implemented contract and schema. `legacy_backend/` is archived. Read each repository's instructions before modifying it; sibling paths provide context rather than authorization for unrelated changes.

## Product and Domain

Taskiller's loop is Capture → Structure → Plan → Execute → Review → Learn. Preserve Project, Sprint, Chore, Work Type, Focus Plan, and Execution Session terminology.

The domain specification describes Projects as root outcomes, Sprints as Project children, and Chores as executable work belonging to a Project, Sprint, or inbox. Work Types supply recommendation inputs. Focus Plans contain ordered segments; Execution Sessions capture actual work and events. Recommendations should be explainable, and analytics should derive from recorded activity rather than an opaque productivity score.

For behavioral changes, consult planning `docs/03-domain-model.md`, `docs/21-state-machines.md`, `docs/06-recommendation-engine.md`, and `docs/22-api-problem-codes.md`, then verify the active service implementation. Research lives in `research/references.md` and `docs/25-research-to-product-matrix.md`.

## Frontend Integration Points

- `src/lib/api/`: shared client, authentication refresh/retry, domain request wrappers, query keys, Problem Details, generated types.
- `src/lib/auth/`: session state; `src/lib/portable/`: import/export; `src/lib/pwa/` and `src/service-worker.js`: connectivity and installation.
- `src/routes/(app)/`: Today, Inbox, Projects, planning, session execution, History, Analytics, Settings, and guide. Public routes cover authentication and account recovery.
- `src/lib/components/`: feature components and shared primitives; `src/app.css`: styles; `static/brand/`: installed assets.
- `tests/e2e/`: browser tests, mock API, and real Django cutover suite.

Preserve in-memory bearer tokens, refresh-cookie authentication, coordinated refresh/retry, ETag/`If-Match` conflict handling, and idempotency keys on applicable writes. Server state and timestamps determine session transitions; client countdowns display them. The current shared fetch client rejects offline mutations. The planning document's queued-offline-write proposal is not current frontend behavior. Keep browser-only APIs guarded during SSR.

Portable changes require coordination with web `docs/export_format/TASKILLER_PORTABLE_IMPORT_EXPORT_SPEC.md` and backend `django_api/portable_import.py`, `portable_views.py`, and `privacy_service.py`. For visual work, consult the planning brand kit and existing frontend assets/components.

## OpenAPI Coordination

Backend `openapi/current.json` is served at `/openapi.json`. Frontend `openapi/taskiller.json` is its committed client snapshot; `src/lib/api/generated/schema.d.ts` is generated, not hand-edited.

Run these commands from `D:/Code/taskiller-web`:

- `npm run api:check`: compare the committed frontend-used surface with the selected backend document. Backend-only additions are allowed; changed referenced operations or schemas fail comparison.
- `npm run api:update`: fetch the selected document and regenerate types. Review and commit the snapshot and generated types together.
- `npm run api:generate`: regenerate types using only the committed snapshot.

Contract scripts choose `TASKILLER_OPENAPI_URL` first, otherwise `TASKILLER_API_URL`, otherwise `PUBLIC_TASKILLER_API_URL`, appending `/openapi.json` to the selected origin. Set the intended local origin explicitly to avoid checking another deployment accidentally. Runtime browser requests use `PUBLIC_TASKILLER_API_URL`.

## Development and Cross-Repository Validation

Backend setup and checks are in the root guide. Start PostgreSQL, apply migrations, and run Django at `http://127.0.0.1:8000`; run the outbox worker separately when the flow requires it. Use Django migrations only.

The frontend requires Node.js >=22 and npm. From its root, use `npm ci`, `npm run dev`, `npm run check`, `npm run build`, and `npm run release:check` as appropriate. No standalone unit-test or lint script is defined in the inspected package configuration.

`npm run test:e2e` runs mocked browser tests. For actual client/server verification, start a dedicated local Django backend and run in PowerShell from the frontend root:

```powershell
$env:TASKILLER_DJANGO_API_URL = 'http://127.0.0.1:8000'
npm run test:e2e:django
```

The Django Playwright configuration requires that variable, sets the frontend API origin from it, builds and previews the web app at `http://127.0.0.1:4173`, and runs `tests/e2e/django-cutover.spec.ts` with one desktop worker. `npm run release:django` adds Svelte/TypeScript checking and a build before the suite. Report checks actually run and missing prerequisites.

Frontend local builds use the Node adapter; CI/Vercel builds use the Vercel adapter. Consult `svelte.config.js`, `vercel.json`, and CI before changing deployment behavior. Keep `.env` files and credentials out of documentation and commits.
