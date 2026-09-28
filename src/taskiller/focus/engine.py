from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from taskiller.focus.schemas import (
    DurationMode,
    FocusPlanSegmentInput,
    FocusPlanSnapshot,
    FocusSegmentKind,
    RecommendationReason,
    RecommendationReasonLabel,
    RecommendationStrategy,
)
from taskiller.work.schemas import LearningMode, WorkCharacteristics

ENGINE_VERSION = "focus-v1.1"
_MIN_RECOMMENDED_BLOCK_SECONDS = 15 * 60
_MAX_RECOMMENDED_BLOCK_SECONDS = 90 * 60
_DEFAULT_BLOCK_SECONDS = 50 * 60
_HIGH_CONTINUITY_BLOCK_SECONDS = 55 * 60
_DEFAULT_BREAK_SECONDS = 8 * 60
_LONG_BREAK_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class SprintChild:
    id: UUID
    name: str
    estimate_seconds: int
    characteristics: WorkCharacteristics


@dataclass(frozen=True, slots=True)
class EnginePreferences:
    strategy: RecommendationStrategy
    work_block_min_seconds: int | None
    work_block_max_seconds: int | None
    personal_work_block_seconds: int | None = None
    personal_sample_size: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedRecommendation:
    strategy: str
    plan: FocusPlanSnapshot
    reasons: list[RecommendationReason]


def _reason(
    code: str,
    label: RecommendationReasonLabel,
    message: str,
) -> RecommendationReason:
    return RecommendationReason(code=code, label=label, message=message)


def _clamp_block(target: int, preferences: EnginePreferences) -> int:
    upper = min(
        preferences.work_block_max_seconds or _MAX_RECOMMENDED_BLOCK_SECONDS,
        _MAX_RECOMMENDED_BLOCK_SECONDS,
    )
    lower = min(
        max(60, preferences.work_block_min_seconds or _MIN_RECOMMENDED_BLOCK_SECONDS),
        upper,
    )
    return max(lower, min(target, upper))


def _work_segment(
    seconds: int,
    linked_work_item_id: UUID,
    *,
    flexible: bool,
    label: str | None = None,
) -> FocusPlanSegmentInput:
    if flexible:
        spread = min(10 * 60, max(2 * 60, seconds // 6))
        return FocusPlanSegmentInput(
            kind=FocusSegmentKind.WORK,
            durationMode=DurationMode.FLEXIBLE,
            targetSeconds=seconds,
            minSeconds=max(60, seconds - spread),
            maxSeconds=min(86_400, seconds + spread),
            linkedWorkItemId=linked_work_item_id,
            optional=False,
            label=label,
        )
    return FocusPlanSegmentInput(
        kind=FocusSegmentKind.WORK,
        durationMode=DurationMode.FIXED,
        targetSeconds=seconds,
        linkedWorkItemId=linked_work_item_id,
        optional=False,
        label=label,
    )


def _break_segment(*, long: bool = False) -> FocusPlanSegmentInput:
    target = _LONG_BREAK_SECONDS if long else _DEFAULT_BREAK_SECONDS
    return FocusPlanSegmentInput(
        kind=FocusSegmentKind.LONG_BREAK if long else FocusSegmentKind.BREAK,
        durationMode=DurationMode.FLEXIBLE,
        targetSeconds=target,
        minSeconds=5 * 60,
        maxSeconds=20 * 60 if long else 10 * 60,
        optional=True,
        label="Long recovery" if long else "Recovery break",
        instructions="Step away from the task; light movement is optional.",
    )


def _resolve_strategy(
    requested: RecommendationStrategy,
    preferences: EnginePreferences,
    characteristics: WorkCharacteristics,
    effort_seconds: int,
) -> tuple[RecommendationStrategy, bool]:
    if requested is not RecommendationStrategy.AUTO:
        return requested, True
    if preferences.strategy is not RecommendationStrategy.AUTO:
        return preferences.strategy, True
    if characteristics.learning_mode is not LearningMode.NONE:
        return RecommendationStrategy.STRUCTURED, False
    if effort_seconds < 20 * 60:
        return RecommendationStrategy.CONTINUOUS, False
    if characteristics.continuity_need.value == "high":
        return RecommendationStrategy.FLEXIBLE, False
    if effort_seconds <= 60 * 60:
        return RecommendationStrategy.CONTINUOUS, False
    return RecommendationStrategy.STRUCTURED, False


def generate_chore_recommendation(
    *,
    work_item_id: UUID,
    effort_seconds: int,
    characteristics: WorkCharacteristics,
    requested_strategy: RecommendationStrategy,
    preferences: EnginePreferences,
    available_time_seconds: int | None,
) -> GeneratedRecommendation:
    if effort_seconds <= 0:
        raise ValueError("effort_seconds must be positive")
    session_effort = min(effort_seconds, available_time_seconds or effort_seconds)
    strategy, preference_used = _resolve_strategy(
        requested_strategy, preferences, characteristics, session_effort
    )
    reasons: list[RecommendationReason] = []
    if preference_used:
        reasons.append(
            _reason(
                "USER_STRATEGY_PREFERENCE",
                RecommendationReasonLabel.USER_PREFERENCE,
                f"The plan uses the selected {strategy.value} strategy.",
            )
        )
    if available_time_seconds is not None:
        reasons.append(
            _reason(
                "AVAILABLE_TIME_CAP",
                RecommendationReasonLabel.PRODUCT_HEURISTIC,
                "The plan is constrained not to exceed the available session-time budget.",
            )
        )
    if characteristics.continuity_need.value == "high" or (
        characteristics.interruption_sensitivity.value == "high"
    ):
        reasons.append(
            _reason(
                "HIGH_CONTINUITY_AVOID_FREQUENT_INTERRUPTION",
                RecommendationReasonLabel.EVIDENCE_MIXED,
                "This work is interruption-sensitive, so the plan avoids frequent forced breaks.",
            )
        )

    if (
        strategy is not RecommendationStrategy.CONTINUOUS
        and characteristics.learning_mode is not LearningMode.NONE
        and session_effort >= 30 * 60
    ):
        segments = _study_segments(
            work_item_id=work_item_id,
            effort_seconds=session_effort,
            learning_mode=characteristics.learning_mode,
            available_time_seconds=available_time_seconds,
        )
        reasons.append(
            _reason(
                "LEARNING_RETRIEVAL_INCLUDED",
                RecommendationReasonLabel.EVIDENCE_BACKED_GENERAL,
                "The plan includes retrieval or review because active retrieval supports learning.",
            )
        )
        return GeneratedRecommendation(
            strategy="structured_learning",
            plan=FocusPlanSnapshot(strategy="structured_learning", segments=segments),
            reasons=reasons,
        )

    if strategy is RecommendationStrategy.CONTINUOUS:
        target = min(session_effort, _MAX_RECOMMENDED_BLOCK_SECONDS)
        if target < session_effort:
            reasons.append(
                _reason(
                    "RECOMMENDED_BLOCK_BOUND",
                    RecommendationReasonLabel.PRODUCT_HEURISTIC,
                    "The timed continuous block is capped at 90 minutes; "
                    "the task can continue in another session.",
                )
            )
        segments = [
            _work_segment(
                target,
                work_item_id,
                flexible=characteristics.continuity_need.value == "high",
            )
        ]
        reasons.append(
            _reason(
                "SHORT_OR_CONTINUOUS_WORK",
                RecommendationReasonLabel.PRODUCT_HEURISTIC,
                "A single work block avoids adding a break when the session does not require one.",
            )
        )
        return GeneratedRecommendation(
            strategy="continuous",
            plan=FocusPlanSnapshot(strategy="continuous", segments=segments),
            reasons=reasons,
        )

    base_target = preferences.personal_work_block_seconds or (
        _HIGH_CONTINUITY_BLOCK_SECONDS
        if characteristics.continuity_need.value == "high"
        else _DEFAULT_BLOCK_SECONDS
    )
    if preferences.personal_work_block_seconds is not None:
        reasons.append(
            _reason(
                "PERSONAL_COMPLETED_SESSION_PATTERN",
                RecommendationReasonLabel.PERSONAL_PATTERN,
                "The work-block target is adjusted toward your recent completed-session "
                f"pattern ({preferences.personal_sample_size} sessions). This is a "
                "descriptive personalization signal, not proof of higher productivity.",
            )
        )
    block_target = _clamp_block(base_target, preferences)
    flexible = strategy is RecommendationStrategy.FLEXIBLE
    segments: list[FocusPlanSegmentInput] = []
    remaining_work = effort_seconds
    remaining_budget = available_time_seconds
    work_blocks = 0
    while remaining_work > 0 and len(segments) < 99:
        if remaining_budget is not None and remaining_budget < 60:
            break
        block = min(block_target, remaining_work)
        if remaining_budget is not None:
            block = min(block, remaining_budget)
        if block < _MIN_RECOMMENDED_BLOCK_SECONDS and segments:
            previous = segments[-1]
            if previous.kind in {FocusSegmentKind.BREAK, FocusSegmentKind.LONG_BREAK}:
                segments.pop()
                if remaining_budget is not None and previous.target_seconds is not None:
                    remaining_budget += previous.target_seconds
                previous = segments[-1]
            if previous.kind is FocusSegmentKind.WORK and previous.target_seconds is not None:
                combined = previous.target_seconds + block
                if combined <= _MAX_RECOMMENDED_BLOCK_SECONDS:
                    previous.target_seconds = combined
                    if previous.max_seconds is not None:
                        previous.max_seconds = min(
                            _MAX_RECOMMENDED_BLOCK_SECONDS, combined + 10 * 60
                        )
                    remaining_work -= block
                    if remaining_budget is not None:
                        remaining_budget -= block
                    continue
        segments.append(
            _work_segment(
                block,
                work_item_id,
                flexible=flexible,
            )
        )
        remaining_work -= block
        if remaining_budget is not None:
            remaining_budget -= block
        work_blocks += 1
        if remaining_work <= 0:
            continue
        pause = _break_segment(long=work_blocks % 2 == 0)
        pause_seconds = pause.target_seconds or 0
        if remaining_budget is not None:
            reserve_for_work = min(remaining_work, _MIN_RECOMMENDED_BLOCK_SECONDS)
            if remaining_budget < pause_seconds + reserve_for_work:
                continue
            remaining_budget -= pause_seconds
        segments.append(pause)
    if any(s.kind in {FocusSegmentKind.BREAK, FocusSegmentKind.LONG_BREAK} for s in segments):
        reasons.append(
            _reason(
                "RECOVERY_BREAKS_FOR_LONGER_SESSION",
                RecommendationReasonLabel.EVIDENCE_BACKED_GENERAL,
                "Longer sessions include flexible recovery breaks to help manage fatigue; "
                "the exact cadence is a product heuristic.",
            )
        )
    reasons.append(
        _reason(
            "BOOTSTRAP_BLOCK_LENGTH",
            RecommendationReasonLabel.PRODUCT_HEURISTIC,
            "Work-block lengths are bootstrap defaults, not a claim of a universally "
            "optimal timer.",
        )
    )
    return GeneratedRecommendation(
        strategy="flexible" if flexible else "structured",
        plan=FocusPlanSnapshot(
            strategy="flexible" if flexible else "structured", segments=segments
        ),
        reasons=reasons,
    )


def _study_segments(
    *,
    work_item_id: UUID,
    effort_seconds: int,
    learning_mode: LearningMode,
    available_time_seconds: int | None,
) -> list[FocusPlanSegmentInput]:
    if learning_mode is LearningMode.RETRIEVAL:
        first_kind = FocusSegmentKind.RETRIEVAL
        first_label = "Active retrieval"
    elif learning_mode is LearningMode.PRACTICE:
        first_kind = FocusSegmentKind.WORK
        first_label = "Practice"
    else:
        first_kind = FocusSegmentKind.WORK
        first_label = "Learn / acquire"

    first = min(30 * 60, max(15 * 60, effort_seconds // 2))
    retrieval = min(10 * 60, max(5 * 60, effort_seconds // 10))
    remaining = max(0, effort_seconds - first - retrieval)
    segments = [
        FocusPlanSegmentInput(
            kind=first_kind,
            durationMode=DurationMode.FLEXIBLE,
            targetSeconds=first,
            minSeconds=max(5 * 60, first - 5 * 60),
            maxSeconds=min(86_400, first + 5 * 60),
            linkedWorkItemId=work_item_id,
            optional=False,
            label=first_label,
        ),
        FocusPlanSegmentInput(
            kind=FocusSegmentKind.RETRIEVAL,
            durationMode=DurationMode.FIXED,
            targetSeconds=retrieval,
            linkedWorkItemId=work_item_id,
            optional=False,
            label="Closed-book retrieval",
            instructions=(
                "Recall, self-test, or answer practice questions without re-reading first."
            ),
        ),
    ]
    if remaining >= 10 * 60:
        break_seconds = min(_DEFAULT_BREAK_SECONDS, max(5 * 60, remaining // 5))
        planned_work = first + retrieval + remaining
        if available_time_seconds is None or planned_work + break_seconds <= available_time_seconds:
            segments.append(
                FocusPlanSegmentInput(
                    kind=FocusSegmentKind.BREAK,
                    durationMode=DurationMode.FLEXIBLE,
                    targetSeconds=break_seconds,
                    minSeconds=5 * 60,
                    maxSeconds=10 * 60,
                    optional=True,
                    label="Recovery break",
                )
            )
    if remaining > 0:
        segments.append(
            FocusPlanSegmentInput(
                kind=FocusSegmentKind.REVIEW,
                durationMode=DurationMode.FLEXIBLE,
                targetSeconds=remaining,
                minSeconds=max(60, remaining - min(5 * 60, remaining // 4)),
                maxSeconds=min(86_400, remaining + min(5 * 60, remaining // 4)),
                linkedWorkItemId=work_item_id,
                optional=False,
                label="Practice / review",
            )
        )
    return segments


def generate_sprint_recommendation(
    *,
    sprint_id: UUID,
    children: list[SprintChild],
    requested_strategy: RecommendationStrategy,
    preferences: EnginePreferences,
    available_time_seconds: int | None,
) -> GeneratedRecommendation:
    del sprint_id
    if not children:
        raise ValueError("a sprint requires remaining chores")
    strategy = requested_strategy
    preference_used = requested_strategy is not RecommendationStrategy.AUTO
    if strategy is RecommendationStrategy.AUTO:
        strategy = preferences.strategy
        preference_used = strategy is not RecommendationStrategy.AUTO
    if strategy is RecommendationStrategy.AUTO:
        strategy = RecommendationStrategy.FLEXIBLE

    reasons = [
        _reason(
            "SPRINT_PRESERVE_USER_ORDER",
            RecommendationReasonLabel.PRODUCT_HEURISTIC,
            "Sprint chores remain in the user's existing order.",
        )
    ]
    if preference_used:
        reasons.append(
            _reason(
                "USER_STRATEGY_PREFERENCE",
                RecommendationReasonLabel.USER_PREFERENCE,
                f"The plan uses the selected {strategy.value} strategy.",
            )
        )
    budget = available_time_seconds
    segments: list[FocusPlanSegmentInput] = []
    accumulated_work = 0
    last_child: SprintChild | None = None
    for child in children:
        if budget is not None and budget < 60:
            break
        target = min(child.estimate_seconds, _clamp_block(_DEFAULT_BLOCK_SECONDS, preferences))
        if budget is not None:
            target = min(target, budget)
        if target <= 0:
            continue
        if last_child is not None:
            context_changed = last_child.characteristics != child.characteristics
            if context_changed:
                transition = 2 * 60
                if budget is None or budget >= transition + target:
                    segments.append(
                        FocusPlanSegmentInput(
                            kind=FocusSegmentKind.TRANSITION,
                            durationMode=DurationMode.FIXED,
                            targetSeconds=transition,
                            optional=True,
                            label="Switch context",
                        )
                    )
                    if budget is not None:
                        budget -= transition
            elif accumulated_work >= 45 * 60:
                pause = _break_segment()
                if budget is None or budget >= (pause.target_seconds or 0) + target:
                    segments.append(pause)
                    if budget is not None:
                        budget -= pause.target_seconds or 0
                    accumulated_work = 0
        flexible = strategy is RecommendationStrategy.FLEXIBLE
        segments.append(
            _work_segment(target, child.id, flexible=flexible, label=child.name)
        )
        accumulated_work += target
        if budget is not None:
            budget -= target
        last_child = child
    if not segments:
        raise ValueError("available time is too short for a sprint plan")
    if available_time_seconds is not None:
        reasons.append(
            _reason(
                "AVAILABLE_TIME_CAP",
                RecommendationReasonLabel.PRODUCT_HEURISTIC,
                "The Sprint plan stops when the requested session-time budget is exhausted.",
            )
        )
    if any(s.kind is FocusSegmentKind.TRANSITION for s in segments):
        reasons.append(
            _reason(
                "CONTEXT_SWITCH_BOUNDARY",
                RecommendationReasonLabel.EVIDENCE_MIXED,
                "Optional transition boundaries are placed between chores whose work "
                "context changes.",
            )
        )
    return GeneratedRecommendation(
        strategy=f"sprint_{strategy.value}",
        plan=FocusPlanSnapshot(strategy=f"sprint_{strategy.value}", segments=segments),
        reasons=reasons,
    )
