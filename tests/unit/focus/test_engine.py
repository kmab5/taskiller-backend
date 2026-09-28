from uuid import uuid4

from taskiller.focus.engine import EnginePreferences, generate_chore_recommendation
from taskiller.focus.schemas import FocusSegmentKind, RecommendationStrategy
from taskiller.work.schemas import (
    IntensityLevel,
    LearningMode,
    PhysicalityLevel,
    WorkCharacteristics,
)


def _chars(*, learning: LearningMode = LearningMode.NONE) -> WorkCharacteristics:
    return WorkCharacteristics(
        cognitiveDemand=IntensityLevel.HIGH,
        interruptionSensitivity=IntensityLevel.HIGH,
        continuityNeed=IntensityLevel.HIGH,
        repetitiveness=IntensityLevel.LOW,
        physicality=PhysicalityLevel.SEDENTARY,
        learningMode=learning,
    )


def _preferences(
    strategy: RecommendationStrategy = RecommendationStrategy.AUTO,
) -> EnginePreferences:
    return EnginePreferences(
        strategy=strategy,
        work_block_min_seconds=None,
        work_block_max_seconds=None,
    )


def test_short_high_continuity_chore_stays_single_block() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=15 * 60,
        characteristics=_chars(),
        requested_strategy=RecommendationStrategy.AUTO,
        preferences=_preferences(),
        available_time_seconds=None,
    )

    assert result.strategy == "continuous"
    assert len(result.plan.segments) == 1
    assert result.plan.segments[0].kind is FocusSegmentKind.WORK
    assert result.plan.segments[0].target_seconds == 15 * 60


def test_long_work_includes_flexible_recovery_without_25_5_assumption() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=2 * 60 * 60,
        characteristics=_chars(),
        requested_strategy=RecommendationStrategy.STRUCTURED,
        preferences=_preferences(),
        available_time_seconds=None,
    )

    work = [s for s in result.plan.segments if s.kind is FocusSegmentKind.WORK]
    breaks = [s for s in result.plan.segments if s.kind is FocusSegmentKind.BREAK]
    assert len(work) >= 2
    assert breaks
    assert all((s.target_seconds or 0) <= 90 * 60 for s in work)
    assert all((s.target_seconds or 0) != 25 * 60 for s in work)


def test_study_plan_adds_retrieval() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=60 * 60,
        characteristics=_chars(learning=LearningMode.ACQUISITION),
        requested_strategy=RecommendationStrategy.AUTO,
        preferences=_preferences(),
        available_time_seconds=None,
    )

    assert result.strategy == "structured_learning"
    assert any(s.kind is FocusSegmentKind.RETRIEVAL for s in result.plan.segments)
    assert any(reason.code == "LEARNING_RETRIEVAL_INCLUDED" for reason in result.reasons)


def test_available_time_caps_recommendation() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=4 * 60 * 60,
        characteristics=_chars(),
        requested_strategy=RecommendationStrategy.CONTINUOUS,
        preferences=_preferences(),
        available_time_seconds=45 * 60,
    )

    assert result.plan.segments[0].target_seconds == 45 * 60
    assert any(reason.code == "AVAILABLE_TIME_CAP" for reason in result.reasons)


def test_available_time_includes_recovery_breaks() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=4 * 60 * 60,
        characteristics=_chars(),
        requested_strategy=RecommendationStrategy.STRUCTURED,
        preferences=_preferences(),
        available_time_seconds=60 * 60,
    )

    elapsed = sum(segment.target_seconds or 0 for segment in result.plan.segments)
    assert elapsed <= 60 * 60


def test_uncapped_study_preserves_estimated_active_work() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=60 * 60,
        characteristics=_chars(learning=LearningMode.ACQUISITION),
        requested_strategy=RecommendationStrategy.AUTO,
        preferences=_preferences(),
        available_time_seconds=None,
    )

    active = sum(
        segment.target_seconds or 0
        for segment in result.plan.segments
        if segment.kind is not FocusSegmentKind.BREAK
    )
    assert active == 60 * 60


def test_explicit_continuous_strategy_is_respected_for_learning_work() -> None:
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=60 * 60,
        characteristics=_chars(learning=LearningMode.ACQUISITION),
        requested_strategy=RecommendationStrategy.CONTINUOUS,
        preferences=_preferences(),
        available_time_seconds=None,
    )

    assert result.strategy == "continuous"
    assert all(segment.kind is FocusSegmentKind.WORK for segment in result.plan.segments)


def test_user_block_preferences_cannot_push_recommendation_above_ninety_minutes() -> None:
    preferences = EnginePreferences(
        strategy=RecommendationStrategy.STRUCTURED,
        work_block_min_seconds=2 * 60 * 60,
        work_block_max_seconds=3 * 60 * 60,
    )
    result = generate_chore_recommendation(
        work_item_id=uuid4(),
        effort_seconds=3 * 60 * 60,
        characteristics=_chars(),
        requested_strategy=RecommendationStrategy.STRUCTURED,
        preferences=preferences,
        available_time_seconds=None,
    )

    work = [segment for segment in result.plan.segments if segment.kind is FocusSegmentKind.WORK]
    assert work
    assert all((segment.target_seconds or 0) <= 90 * 60 for segment in work)
