# Round 6 — Analytics and Personalization

Round 6 turns Taskiller's immutable execution history into interpretable analytics and cautiously feeds sufficiently supported personal patterns back into Focus Plan recommendations.

## Added capabilities

- deterministic Session interval reconstruction;
- active-work, break and pause totals;
- uninterrupted-work distributions;
- estimate calibration for completed Chores;
- planned-start delay statistics;
- required-segment adherence;
- user summary analytics;
- Work Type analytics;
- Project/Sprint/Chore rollups using historical ancestry snapshots;
- timezone-aware daily/weekly time series;
- local-hour focus/activity patterns;
- review-aware focus-pattern summaries;
- history-informed work-block personalization.

No generic productivity/efficiency score is introduced.

## Historical stability

`execution_sessions.work_context_snapshot_json` is immutable after Session creation and records Work Type, estimate, planned start and ancestry for the target/linked work. The database trigger rejects later mutation of this snapshot just like the Focus Plan and recommendation snapshots.

The migration backfills existing Sessions using current WorkItem context. New Sessions capture full target and linked-Chore context at creation time.

## Personalization contract

The Focus engine version advances to `focus-v1.1`. Eligible personal history can change the bootstrap work-block target for structured/flexible Chore recommendations. Explicit user strategy and min/max block preferences remain authoritative constraints.

Recommendations affected by personal history are persisted with:

- `provenance = history_informed`;
- a `personal_pattern` reason;
- the exact sample size, median focus score and chosen historical target in `inputSnapshot.personalizationSignal`.

This makes every personalized recommendation reproducible and auditable.

## Performance posture

Round 6 derives analytics directly from Sessions and Events rather than introducing a cache/materialized aggregate that could become stale. This is the simpler source-of-truth design for v1. Round 7's worker/outbox infrastructure gives us a clean place to add precomputed aggregates later if production volume requires them without changing the public API.
