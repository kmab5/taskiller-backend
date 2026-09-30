from taskiller.focus.models import FocusPlanModel, FocusPlanRecommendationModel
from taskiller.focus.schemas import (
    DurationMode,
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
    FocusPlanSnapshot,
    FocusPlanSource,
    FocusSegmentKind,
    RecommendationProvenance,
    RecommendationReason,
)


def recommendation_to_response(
    row: FocusPlanRecommendationModel,
) -> FocusPlanRecommendation:
    return FocusPlanRecommendation(
        id=row.id,
        work_item_id=row.work_item_id,
        engine_version=row.engine_version,
        provenance=RecommendationProvenance(row.provenance),
        plan=FocusPlanSnapshot.model_validate(row.plan_snapshot_json),
        reasons=[RecommendationReason.model_validate(item) for item in row.reasons_json],
        created_at=row.created_at,
    )


def focus_plan_to_response(row: FocusPlanModel) -> FocusPlan:
    return FocusPlan(
        id=row.id,
        work_item_id=row.work_item_id,
        recommendation_id=row.recommendation_id,
        source=FocusPlanSource(row.source),
        name=row.name,
        template=row.is_template,
        segments=[
            FocusPlanSegment(
                id=segment.id,
                index=segment.segment_index,
                kind=FocusSegmentKind(segment.kind),
                duration_mode=DurationMode(segment.duration_mode),
                target_seconds=segment.target_seconds,
                min_seconds=segment.min_seconds,
                max_seconds=segment.max_seconds,
                linked_work_item_id=segment.linked_work_item_id,
                optional=segment.optional,
                label=segment.label,
                instructions=segment.instructions,
            )
            for segment in row.segments
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )
