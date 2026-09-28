# Analytics and Personalization

Taskiller analytics are derived from the authoritative Execution Session and Session Event history. The backend does not infer productivity from wall-clock presence or from a generic "efficiency score". It reports observable quantities such as active work, breaks, pauses, estimate error, plan adherence, completion counts, focus reviews and uninterrupted-work patterns.

## Time derivation

The server reconstructs each Session chronologically from its immutable Focus Plan snapshot and append-only Events.

- `segment_started` / `break_started` begin an active interval.
- `paused` closes the current active interval and begins paused time.
- `resumed` ends paused time and resumes the same segment.
- `segment_completed` / `break_ended` close the current interval.
- `segment_skipped` advances without inventing work time.
- terminal Events close any remaining active/pause interval.

Open Sessions are measured only through the current server time. Query windows clip totals at their boundaries; partially clipped intervals are deliberately excluded from uninterrupted-work percentile samples so a reporting boundary cannot create an artificial short focus block.

## Historical context snapshots

Round 6 adds an immutable `workContextSnapshot` to each new Execution Session. It captures the target and Focus-Plan-linked WorkItems at Session start, including:

- WorkItem kind and parent ancestry;
- Work Type id/slug;
- effort estimate;
- planned start time.

This keeps old analytics stable if the user later edits an estimate, changes a Work Type, or moves a Chore between Sprints/Projects. Existing pre-Round-6 Sessions are migration-backfilled with the best context available at migration time.

## Public analytics API

All ranges are explicit half-open intervals `[from, to)` and both datetimes must include an offset.

- `GET /analytics/summary` — user totals, completion counts, medians and plan adherence.
- `GET /analytics/work-types` — active time, session count, completion rate and calibration grouped by Work Type.
- `GET /analytics/work-items/{id}` — analytics for one item and its descendants where applicable.
- `GET /analytics/timeseries?bucket=day|week` — plot-ready zero-filled buckets using the user's IANA timezone and configured week start (`0=Sunday`, `1=Monday`, …, `6=Saturday`).
- `GET /analytics/focus-patterns` — descriptive uninterrupted-work distributions plus local-hour activity patterns.

Estimate error is `tracked active work − estimated effort` for Chores completed inside the query range. Taskiller aggregates tracked work across Sessions up to the completion time rather than assuming one Session equals one task.

## Personalization

The recommendation engine remains deterministic. History can adjust a Chore's structured/flexible work-block target only when there is enough completed-session evidence for that Work Type.

Eligibility is intentionally conservative:

- at least 5 completed Sessions plus at least 3 focus reviews with median focus score >= 3; or
- at least 8 completed Sessions when review data is sparse;
- at least 5 qualifying uninterrupted-work intervals of 5 minutes or longer.

Eligible medians are rounded to five minutes and clamped to 15–90 minutes, then still constrained by explicit user min/max preferences. The resulting recommendation uses `history_informed` provenance and a `personal_pattern` reason that explicitly describes the signal as historical/descriptive rather than proof of increased productivity.

Study/retrieval specialization and explicit `continuous` choices remain higher-order behavior; history does not silently override those semantics.
