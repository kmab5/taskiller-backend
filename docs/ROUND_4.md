# Round 4 — Focus & Recommendation Engine

Round 4 adds the execution-planning layer between WorkItems and the Execution Sessions that arrive in Round 5.

## Delivered

- immutable `focus_plan_recommendations` with input, plan and rationale snapshots
- deterministic engine version `focus-v1.0`
- qualitative provenance: `bootstrap` or `preference_informed`
- Chore recommendations using effective Work characteristics, effort, user preferences and optional session-time limits
- Sprint recommendations that preserve Chore order and link each work segment to exactly one Chore
- study specialization with retrieval/review segments
- evidence-labelled rationale objects; no numeric confidence or claims of an optimal universal cadence
- editable/versioned Focus Plans with normalized ordered segments
- manual, recommendation-derived and reusable template plans
- ETag/If-Match concurrency for Focus Plan edits/deletes
- Idempotency-Key protection for recommendation generation and Focus Plan creation
- soft deletion and cursor pagination for Focus Plans
- PostgreSQL constraints for source/template invariants and segment duration shapes

## Deliberate boundary

Round 4 does **not** infer historical personalization yet because completed Execution Sessions do not exist until Round 5. The engine schema already reserves `history_informed`; Round 6 will activate that provenance after enough real user history exists.

A recommendation is immutable. A user can save it as a Focus Plan and edit that plan freely while retaining `recommendationId`, preserving the distinction between what Taskiller suggested and what the user chose.

## Recommendation safety/product bounds

Generated recommendations cap individual suggested work blocks at 90 minutes, even when a stored block preference is longer; users remain free to build a custom plan outside that range. Optional `availableTimeSeconds` is an elapsed-session budget, so generated work plus suggested breaks stays within it. Explicit strategy requests are respected. Breaks are flexible/optional where appropriate. Pomodoro is not treated as a universal default.
