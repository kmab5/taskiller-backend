# Django Migration — Phase 4 Work Domain

Prepared against:

- backend `main`: `b1de8835a1eb348a7389378297187e76c9715c51`
- frontend `main`: `c49bedaf7dc33dc13403d298be092b02562def09`

This package is cumulative Phase 1 + 2 + 3 + 4 because the earlier phases are not on backend main.

## Migrated Work API

- GET/POST `/api/v1/work-types`
- GET/PATCH/DELETE `/api/v1/work-types/{workTypeId}`
- GET/POST `/api/v1/work-items`
- GET/PATCH/DELETE `/api/v1/work-items/{workItemId}`
- GET `/api/v1/work-items/{workItemId}/children`
- GET `/api/v1/work-items/{workItemId}/tree`
- POST `/api/v1/work-items/{workItemId}/reorder`
- GET `/api/v1/projects/{projectId}/next-action`

## Preserved behavior

- built-in Work Types are global and immutable
- custom Work Types are owner-scoped
- custom slug uniqueness
- Work Type ETags
- Project/Sprint/Chore containment rules
- PostgreSQL hierarchy trigger remains active
- bounded tree traversal
- soft-deleted Work Items are hidden by default
- cursor pagination
- work-item state transition matrix
- terminal timestamps
- project-only target date validation
- Work Type characteristic defaults + per-item overrides
- effective characteristics
- item ETags / If-Match
- idempotent create and reorder
- explicit sibling namespace locking
- spaced position allocation and rebalance
- live-child delete protection
- Project next-action traversal

## Framework split after Phase 4

Django/DRF now implements:

- Auth
- User
- Work

FastAPI still implements:

- Focus
- Execution
- Analytics
- worker/retention internals

Production Render remains FastAPI.
