# Work Domain

Round 3 implements Taskiller's structural work model. The Work domain is independent of the future Focus and Execution domains: Projects and Sprints organize work, while Chores are the atomic executable units. A Sprint may itself be returned as a next action when it is actionable but has no actionable Chore.

## Hierarchy

The allowed containment graph is deliberately bounded:

```text
Project
├── Sprint
│   └── Chore
└── Chore

Chore may also be top-level.
```

Rules:

- Projects never have parents.
- Sprints must belong directly to a Project.
- Chores may be top-level or belong to a Project or Sprint.
- Parents and children must have the same owner.
- Deleted WorkItems cannot be parents.
- A WorkItem cannot parent itself.

The service validates these rules and PostgreSQL independently enforces them with the `work_items_validate_hierarchy` trigger. The trigger also keeps kind/owner immutable, guards soft-deletion of parents with live children, and rejects invalid state transitions. This prevents invalid writes from scripts, future workers, or accidental ORM bypasses.

## WorkItem state machine

Canonical states are `draft`, `ready`, `in_progress`, `completed`, `cancelled`, and `archived`.

Allowed transitions:

```text
draft       -> ready | cancelled
ready       -> in_progress | completed | cancelled | archived
in_progress -> completed | cancelled
completed   -> ready | archived
cancelled   -> ready | archived
archived    -> ready
```

A transition to `completed`, `cancelled`, or `archived` records its corresponding server timestamp. Reopening to `ready` clears terminal timestamps. Database constraints require the active terminal state to have its timestamp.

Deletion is soft deletion for WorkItems. A live item with live children cannot be deleted. Custom WorkTypes are hard-deleted; PostgreSQL sets referencing `workTypeId` values to null while preserving WorkItem characteristic overrides.

## Ordering

Sibling WorkItems share a `position` namespace and are initially spaced by 1024. Reorder requests position an item before or after another live sibling. The service normally fills a numeric gap; when gaps are exhausted it rebalances siblings to spaced positions. Reordering is protected by row locks, ETags and idempotency keys.

The API intentionally exposes `position` for deterministic clients, but clients should use the reorder endpoint instead of calculating positions themselves.

## Work Types and characteristics

Taskiller ships global immutable WorkTypes and supports user-owned custom WorkTypes. A WorkType supplies defaults for:

- cognitive demand
- interruption sensitivity
- continuity need
- repetitiveness
- physicality
- learning mode

A WorkItem may override any subset. API responses include both `characteristicOverrides` and resolved `effectiveCharacteristics`. These fields become input to the Round 4 recommendation engine.

Built-in types seeded by migration are study/learning, reading, writing, programming, problem solving, creative generation, brainstorming/planning, administration, communication, repetitive processing and physical chore.

## Concurrency and idempotency

Mutable WorkTypes and WorkItems use ETags. Clients read the ETag and send it back using `If-Match`; stale or absent values receive `412 precondition_failed` from the domain service.

Creation and reorder operations require an `Idempotency-Key` (8-200 characters). Idempotency records are scoped to user + operation, hash the canonical request payload, and expire after the configured TTL. Reusing a key with the same request replays the original response. Reusing it with different content returns `409 idempotency_key_reused`.

## Query behavior

`GET /work-items` uses stable descending `(createdAt, id)` cursor pagination. It can filter by kind, status and parent and can explicitly include soft-deleted items.

`GET /work-items/{id}/tree` returns the complete bounded subtree for the three-level Taskiller hierarchy.

`GET /projects/{id}/next-action` walks children in sibling order. It skips terminal branches, prefers an actionable Chore inside a Sprint, and otherwise may return the actionable Sprint. A terminal Project has no next action.

## Round 3 endpoints

```text
GET    /api/v1/work-types
POST   /api/v1/work-types
GET    /api/v1/work-types/{workTypeId}
PATCH  /api/v1/work-types/{workTypeId}
DELETE /api/v1/work-types/{workTypeId}

GET    /api/v1/work-items
POST   /api/v1/work-items
GET    /api/v1/work-items/{workItemId}
PATCH  /api/v1/work-items/{workItemId}
DELETE /api/v1/work-items/{workItemId}
GET    /api/v1/work-items/{workItemId}/children
GET    /api/v1/work-items/{workItemId}/tree
POST   /api/v1/work-items/{workItemId}/reorder

GET    /api/v1/projects/{projectId}/next-action
```
