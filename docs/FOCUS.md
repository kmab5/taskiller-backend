# Focus Domain

## Resources

### FocusPlanRecommendation

An immutable explanation snapshot produced by the deterministic engine. It stores:

- owner and target WorkItem
- engine version
- provenance
- input snapshot used by the engine
- generated plan snapshot
- evidence/product rationale objects
- creation timestamp

Recommendations are never silently regenerated when rules change.

### FocusPlan

The user's selected execution plan. It can be manual, recommendation-derived, or a reusable template. It has a version/ETag and ordered normalized segments.

### FocusPlanSegment

Supported kinds are `work`, `break`, `long_break`, `retrieval`, `review`, `planning`, and `transition`. Duration modes are `fixed`, `flexible`, and `open`.

Fixed/flexible segments require a target duration. Flexible segments may additionally declare minimum/maximum bounds. Break/transition segments cannot reference WorkItems.

## Target rules

- Projects cannot be focused directly; clients should resolve `/projects/{id}/next-action` first.
- Chore plans may link segments only to that Chore.
- Sprint plans may link segments only to direct child Chores.
- Generic templates are unbound and cannot contain WorkItem links.

## Recommendation inputs

The v1 engine consumes effective Work characteristics, effort estimates, user strategy/block preferences, and an optional available-time limit. When supplied, `availableTimeSeconds` caps the planned elapsed segment targets, including suggested recovery breaks.

An explicit strategy choice is respected. For example, learning work requested as `continuous` is not silently converted into a retrieval schedule; retrieval specialization applies when the resolved strategy is structured/flexible.

If a Chore has neither a usable effort estimate nor `availableTimeSeconds`, or lacks complete effective characteristics, recommendation generation returns `recommendation_context_incomplete`.

## Evidence posture

Reason labels distinguish `evidence_backed_general`, `evidence_mixed`, `product_heuristic`, `personal_pattern`, and `user_preference`. Round 4 emits the first, second, third and fifth categories; `personal_pattern` is activated only after Execution/Analytics data exists.
