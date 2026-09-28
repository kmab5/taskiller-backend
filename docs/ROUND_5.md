# Round 5 — Execution Engine

Round 5 turns Focus Plans into durable, cross-device execution state. The backend does not run an in-memory countdown. PostgreSQL stores Session state, immutable plan/recommendation snapshots, authoritative server timestamps and append-only Session Events; any client can reconstruct the timer after a refresh, device switch or server restart.

## Resources

- `ExecutionSession` — one real attempt to execute a Chore or Sprint.
- `SessionEvent` — immutable state-transition/audit record.
- `SessionReview` — editable post-session subjective feedback.

A Session targets a Chore or Sprint, never a Project, and snapshots the selected Focus Plan at start. Later Focus Plan changes cannot rewrite that Session's history.

## Session state

Canonical states are `running`, `paused`, `completed` and `abandoned`. PostgreSQL enforces at most one `running`/`paused` Session per user.

Starting a Session records `session_started` plus an initial `segment_started` (or `break_started` when appropriate). Completing/skipping a segment advances `currentSegmentIndex` but does **not** pretend the next segment started: `currentSegmentStartedAt` remains null until the client explicitly starts it.

Pausing records `pausedAt`. On resume, the aggregate shifts `currentSegmentStartedAt` forward by the pause interval, so client countdown reconstruction naturally excludes manual pause time.

## Event API

State changes are Event resources rather than RPC endpoints:

```http
POST /api/v1/execution-sessions/{id}/events
Idempotency-Key: 6f40...
If-Match: "execution-session:{id}:v4"

{"type":"paused"}
```

Every accepted event increments the Session version. A stale device receives `412`. Exact event retries return the original event **and the original post-event Session snapshot**, even if another device subsequently advanced the Session. Reusing the same idempotency key for a materially different event returns `409`.

Supported event types:

- `paused` / `resumed`
- `segment_started` / `segment_completed` / `segment_skipped`
- `break_started` / `break_ended`
- `work_item_completed`
- `session_completed` / `session_abandoned`

`session_started` is server-created only.

## WorkItem interaction

Starting executable work moves a Draft through `ready` to `in_progress`, or a Ready item directly to `in_progress`. Session completion does not silently complete the WorkItem. Completion is explicit through `work_item_completed`.

For a Chore Session, that event can only complete the Session's Chore. For a Sprint Session it can complete a direct child Chore, selected by `payload.workItemId` or inferred from the current Focus Plan segment's linked Chore.

Timer target expiry never invents user behavior. If all clients are closed beyond a segment target, reopening the app shows the elapsed/overdue state and the user/client resolves the next transition.

## Reviews

A terminal Session can receive an idempotent review with optional 1–5 focus, fatigue, difficulty and satisfaction scores plus a note. Reviews are editable user interpretation; Events and Session snapshots are immutable history.

## Database hardening

Round 5 adds database checks/triggers for:

- one-open-Session-per-user;
- Chore/Sprint-only Session targets;
- owner consistency across WorkItem, Focus Plan, Recommendation, Session Event and Review;
- immutable Session identity and snapshots;
- terminal Session state immutability;
- exact version increments on Session updates;
- append-only Session Event rows.
