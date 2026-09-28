# Round 3 — Work Model

Round 3 turns the authenticated Taskiller backend into a usable task-structure API. It implements Work Types plus the Project/Sprint/Chore hierarchy that later Focus, Execution and Analytics rounds build on.

## Delivered

- global seeded and user-defined Work Types
- work-characteristic defaults and per-WorkItem overrides
- Project, Sprint and Chore CRUD
- application and PostgreSQL hierarchy enforcement
- explicit WorkItem state machine and terminal timestamps
- shared sibling ordering with deterministic reorder operations
- Project tree and next-action queries
- cursor-paginated WorkItem listing and filters
- soft deletion for WorkItems
- ETag optimistic concurrency on mutable resources
- database-backed idempotency for create/reorder operations
- custom WorkType deletion with `ON DELETE SET NULL`
- Round 3 OpenAPI contract and integration/unit coverage

## Persistence changes

Migration `20260928_0002_work_model.py` adds:

```text
idempotency_records
work_types
work_items
```

It also seeds the built-in WorkTypes and installs the `work_items_validate_hierarchy` PostgreSQL trigger. Migration downgrade removes the trigger/function and all Round 3 tables/indexes.

## Boundary decisions

Round 3 deliberately does not create Focus Plans, timers or Execution Sessions. `in_progress` is currently a WorkItem planning/status state; Round 5 will connect execution state to Session invariants.

Work Type characteristics are descriptive inputs, not productivity claims. Round 4 owns the evidence-informed recommendation rules that interpret them.

Dependencies between WorkItems are also outside Round 3. Parent/child means containment only; it is not overloaded to mean "must happen before."

## Cross-device safety

Work mutations use two different mechanisms for two different failure modes:

- **ETag + If-Match** prevents a client from overwriting a newer representation.
- **Idempotency-Key** prevents retried create/reorder requests from performing the action twice.

This distinction is important for web/mobile/desktop clients operating concurrently against the same account.

See `docs/WORK.md` for domain semantics and `VALIDATION.md` for the verification performed on this artifact.
