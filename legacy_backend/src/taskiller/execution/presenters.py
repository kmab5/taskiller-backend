from taskiller.execution.models import ExecutionSessionModel, SessionEventModel, SessionReviewModel
from taskiller.execution.schemas import (
    ExecutionSession,
    ExecutionSessionState,
    SessionEvent,
    SessionEventType,
    SessionReview,
)
from taskiller.focus.schemas import FocusPlanSnapshot


def execution_session_to_response(row: ExecutionSessionModel) -> ExecutionSession:
    return ExecutionSession(
        id=row.id,
        work_item_id=row.work_item_id,
        focus_plan_id=row.focus_plan_id,
        recommendation_id=row.recommendation_id,
        state=ExecutionSessionState(row.state),
        current_segment_index=row.current_segment_index,
        session_started_at=row.session_started_at,
        current_segment_started_at=row.current_segment_started_at,
        paused_at=row.paused_at,
        ended_at=row.ended_at,
        plan_snapshot=FocusPlanSnapshot.model_validate(row.plan_snapshot_json),
        recommendation_snapshot=row.recommendation_snapshot_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


def session_event_to_response(row: SessionEventModel) -> SessionEvent:
    return SessionEvent(
        id=row.id,
        session_id=row.session_id,
        type=SessionEventType(row.type),
        occurred_at=row.occurred_at,
        client_occurred_at=row.client_occurred_at,
        segment_index=row.segment_index,
        payload=row.payload_json,
    )


def session_review_to_response(row: SessionReviewModel) -> SessionReview:
    return SessionReview(
        session_id=row.session_id,
        focus_score=row.focus_score,
        fatigue_score=row.fatigue_score,
        difficulty_score=row.difficulty_score,
        satisfaction_score=row.satisfaction_score,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )
