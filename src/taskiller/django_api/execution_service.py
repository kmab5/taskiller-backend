from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.db.models import Q
from pydantic import BaseModel, ValidationError

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.idempotency import claim_idempotency, complete_idempotency
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import (
    ExecutionSession,
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
    SessionEvent,
    SessionReview,
    TaskillerUser,
    WorkItem,
    WorkType,
)
from taskiller.execution.schemas import (
    CreateSessionEventRequest,
    ExecutionSessionState,
    SessionEventType,
    StartExecutionSessionRequest,
    UpsertSessionReviewRequest,
)
from taskiller.focus.schemas import (
    DurationMode,
    FocusPlanSegmentInput,
    FocusPlanSnapshot,
    FocusSegmentKind,
)
from taskiller.users.etag import make_etag
from taskiller.work.schemas import WorkItemKind, WorkItemStatus

_TERMINAL_WORK_STATES = {
    WorkItemStatus.COMPLETED.value,
    WorkItemStatus.CANCELLED.value,
    WorkItemStatus.ARCHIVED.value,
}
_BREAK_KINDS = {FocusSegmentKind.BREAK.value, FocusSegmentKind.LONG_BREAK.value}


def validate_payload[T: BaseModel](model: type[T], data: Any) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "One or more request values are invalid.",
            meta={
                "errors": [
                    {
                        "type": item.get("type"),
                        "loc": ["body", *item.get("loc", ())],
                        "msg": item.get("msg"),
                    }
                    for item in exc.errors()
                ]
            },
        ) from exc


def require_idempotency_key(value: str | None) -> str:
    key = value or ""
    if not 8 <= len(key) <= 200:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "Idempotency-Key must be between 8 and 200 characters.",
        )
    return key


def require_etag(if_match: str | None, expected: str) -> None:
    if if_match is None or if_match.strip() != expected:
        raise TaskillerAPIError(
            412,
            "precondition_failed",
            "Resource version mismatch",
            "Refresh the resource and retry using its latest ETag.",
            headers={"ETag": expected},
        )


def _session_response(row: ExecutionSession) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workItemId": str(row.work_item_id),
        "focusPlanId": str(row.focus_plan_id),
        "recommendationId": (
            str(row.recommendation_id) if row.recommendation_id is not None else None
        ),
        "state": row.state,
        "currentSegmentIndex": row.current_segment_index,
        "sessionStartedAt": row.session_started_at.isoformat(),
        "currentSegmentStartedAt": (
            row.current_segment_started_at.isoformat()
            if row.current_segment_started_at is not None
            else None
        ),
        "pausedAt": row.paused_at.isoformat() if row.paused_at is not None else None,
        "endedAt": row.ended_at.isoformat() if row.ended_at is not None else None,
        "planSnapshot": row.plan_snapshot_json,
        "recommendationSnapshot": row.recommendation_snapshot_json,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "version": row.version,
    }


def _event_response(row: SessionEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "sessionId": str(row.session_id),
        "type": row.type,
        "occurredAt": row.occurred_at.isoformat(),
        "clientOccurredAt": (
            row.client_occurred_at.isoformat() if row.client_occurred_at is not None else None
        ),
        "segmentIndex": row.segment_index,
        "payload": row.payload_json,
    }


def _review_response(row: SessionReview) -> dict[str, Any]:
    return {
        "sessionId": str(row.session_id),
        "focusScore": row.focus_score,
        "fatigueScore": row.fatigue_score,
        "difficultyScore": row.difficulty_score,
        "satisfactionScore": row.satisfaction_score,
        "note": row.note,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "version": row.version,
    }


class DjangoExecutionService:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.idempotency_ttl_hours = taskiller_settings().idempotency_ttl_hours

    def start_session(
        self,
        payload: StartExecutionSessionRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_body = payload.model_dump(mode="json", by_alias=True)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope="execution-sessions:start",
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            TaskillerUser.objects.select_for_update().get(id=self.owner_id)
            work_item = (
                WorkItem.objects.select_for_update()
                .filter(
                    id=payload.work_item_id,
                    owner_id=self.owner_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if work_item is None:
                raise self._not_found("work_item_not_found", "Work item not found")
            if work_item.kind not in {WorkItemKind.CHORE.value, WorkItemKind.SPRINT.value}:
                raise TaskillerAPIError(
                    422,
                    "project_not_executable",
                    "Projects cannot be executed directly",
                    "Resolve the Project to a Chore or Sprint before starting a Session.",
                )
            if work_item.status in _TERMINAL_WORK_STATES:
                raise TaskillerAPIError(
                    409,
                    "work_item_terminal",
                    "Work item is terminal",
                    "Completed, cancelled, or archived work cannot start a new Session.",
                )

            focus_plan = (
                FocusPlan.objects.select_for_update()
                .filter(
                    id=payload.focus_plan_id,
                    owner_id=self.owner_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if focus_plan is None:
                raise self._not_found("focus_plan_not_found", "Focus Plan not found")
            if focus_plan.is_template:
                raise TaskillerAPIError(
                    422,
                    "focus_plan_template_unexecutable",
                    "Template cannot be executed directly",
                    "Create a non-template Focus Plan before starting a Session.",
                )
            if focus_plan.work_item_id != work_item.id:
                raise TaskillerAPIError(
                    422,
                    "focus_plan_work_item_mismatch",
                    "Focus Plan does not match work item",
                    "The selected Focus Plan must be bound to the Session work item.",
                )

            segments = list(
                FocusPlanSegment.objects.filter(focus_plan_id=focus_plan.id).order_by(
                    "segment_index"
                )
            )
            if not segments:
                raise TaskillerAPIError(
                    422,
                    "empty_focus_plan",
                    "Focus Plan has no segments",
                )

            recommendation_id = payload.recommendation_id or focus_plan.recommendation_id
            recommendation_snapshot: dict[str, object] | None = None
            if recommendation_id is not None:
                recommendation = FocusPlanRecommendation.objects.filter(
                    id=recommendation_id,
                    owner_id=self.owner_id,
                ).first()
                if recommendation is None:
                    raise self._not_found(
                        "recommendation_not_found",
                        "Recommendation not found",
                    )
                if recommendation.work_item_id != work_item.id:
                    raise TaskillerAPIError(
                        422,
                        "recommendation_work_item_mismatch",
                        "Recommendation does not match work item",
                    )
                recommendation_snapshot = {
                    "id": str(recommendation.id),
                    "engineVersion": recommendation.engine_version,
                    "provenance": recommendation.provenance,
                    "strategy": recommendation.strategy,
                    "input": recommendation.input_snapshot_json,
                    "plan": recommendation.plan_snapshot_json,
                    "reasons": recommendation.reasons_json,
                    "createdAt": recommendation.created_at.isoformat(),
                }

            plan_snapshot = self._snapshot_plan(segments)
            work_context_snapshot = self._snapshot_work_context(
                work_item,
                segments,
            )

            now = utc_now()
            initial_segment_at = now + timedelta(microseconds=1)
            row = ExecutionSession(
                id=uuid4(),
                owner_id=self.owner_id,
                work_item_id=work_item.id,
                focus_plan_id=focus_plan.id,
                recommendation_id=recommendation_id,
                state=ExecutionSessionState.RUNNING.value,
                current_segment_index=0,
                session_started_at=now,
                current_segment_started_at=initial_segment_at,
                paused_at=None,
                ended_at=None,
                plan_snapshot_json=plan_snapshot.model_dump(mode="json", by_alias=True),
                recommendation_snapshot_json=recommendation_snapshot,
                work_context_snapshot_json=work_context_snapshot,
                created_at=now,
                updated_at=now,
                version=1,
            )
            try:
                row.save(force_insert=True)
            except IntegrityError as exc:
                raise TaskillerAPIError(
                    409,
                    "open_session_exists",
                    "Another Session is already open",
                    "Complete or abandon the existing Session before starting another.",
                ) from exc

            self._move_work_item_to_in_progress(work_item, now)
            response = _session_response(row)

            initial_kind = plan_snapshot.segments[0].kind
            initial_type = (
                SessionEventType.BREAK_STARTED
                if initial_kind.value in _BREAK_KINDS
                else SessionEventType.SEGMENT_STARTED
            )
            SessionEvent.objects.bulk_create(
                [
                    SessionEvent(
                        id=uuid4(),
                        session_id=row.id,
                        owner_id=self.owner_id,
                        type=SessionEventType.SESSION_STARTED.value,
                        occurred_at=now,
                        client_occurred_at=None,
                        segment_index=None,
                        idempotency_key=f"start:{idempotency_key}"[:200],
                        request_hash=self._hash_payload({"type": "session_started"}),
                        payload_json={},
                        result_session_snapshot_json=response,
                        created_at=now,
                    ),
                    SessionEvent(
                        id=uuid4(),
                        session_id=row.id,
                        owner_id=self.owner_id,
                        type=initial_type.value,
                        occurred_at=initial_segment_at,
                        client_occurred_at=None,
                        segment_index=0,
                        idempotency_key=f"initial:{idempotency_key}"[:200],
                        request_hash=self._hash_payload(
                            {
                                "type": initial_type.value,
                                "segmentIndex": 0,
                            }
                        ),
                        payload_json={},
                        result_session_snapshot_json=response,
                        created_at=now,
                    ),
                ]
            )

            complete_idempotency(
                owner_id=self.owner_id,
                scope="execution-sessions:start",
                key=idempotency_key,
                response_status=201,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_active_session(self) -> dict[str, object]:
        row = (
            ExecutionSession.objects.filter(
                owner_id=self.owner_id,
                state__in=[
                    ExecutionSessionState.RUNNING.value,
                    ExecutionSessionState.PAUSED.value,
                ],
            )
            .order_by("-session_started_at")
            .first()
        )
        return {"session": _session_response(row) if row is not None else None}

    def get_session(self, session_id: UUID) -> dict[str, Any]:
        row = self._session(session_id)
        if row is None:
            raise self._not_found(
                "execution_session_not_found",
                "Execution Session not found",
            )
        return _session_response(row)

    def list_sessions(
        self,
        *,
        limit: int,
        cursor: str | None,
        work_item_id: UUID | None,
        state: ExecutionSessionState | None,
        from_at: datetime | None,
        to_at: datetime | None,
    ) -> dict[str, Any]:
        from_at = self._normalize_datetime_bound(from_at, "from")
        to_at = self._normalize_datetime_bound(to_at, "to")
        if from_at is not None and to_at is not None and from_at >= to_at:
            raise TaskillerAPIError(
                422,
                "invalid_time_range",
                "Invalid time range",
                "from must be before to.",
            )

        query = ExecutionSession.objects.filter(owner_id=self.owner_id)
        if work_item_id is not None:
            query = query.filter(work_item_id=work_item_id)
        if state is not None:
            query = query.filter(state=state.value)
        if from_at is not None:
            query = query.filter(session_started_at__gte=from_at)
        if to_at is not None:
            query = query.filter(session_started_at__lt=to_at)
        if cursor is not None:
            started_at, row_id = self._decode_cursor(cursor)
            query = query.filter(
                Q(session_started_at__lt=started_at)
                | Q(session_started_at=started_at, id__lt=row_id)
            )

        rows = list(query.order_by("-session_started_at", "-id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].session_started_at, rows[-1].id)
            if has_more and rows
            else None
        )
        return {
            "items": [_session_response(row) for row in rows],
            "page": {
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
        }

    def append_event(
        self,
        session_id: UUID,
        payload: CreateSessionEventRequest,
        idempotency_key: str,
        if_match: str | None,
    ) -> dict[str, Any]:
        digest = self._hash_payload(payload.model_dump(mode="json", by_alias=True))

        with transaction.atomic():
            TaskillerUser.objects.select_for_update().get(id=self.owner_id)
            row = self._session(session_id, lock=True)
            if row is None:
                raise self._not_found(
                    "execution_session_not_found",
                    "Execution Session not found",
                )

            existing = SessionEvent.objects.filter(
                session_id=row.id,
                idempotency_key=idempotency_key,
            ).first()
            if existing is not None:
                if existing.request_hash != digest:
                    raise TaskillerAPIError(
                        409,
                        "idempotency_key_reused",
                        "Idempotency key reused",
                        "The same Idempotency-Key was already used with a different event.",
                    )
                return {
                    "event": _event_response(existing),
                    "session": existing.result_session_snapshot_json,
                }

            require_etag(
                if_match,
                make_etag("execution-session", row.id, row.version),
            )
            if row.state in {
                ExecutionSessionState.COMPLETED.value,
                ExecutionSessionState.ABANDONED.value,
            }:
                raise TaskillerAPIError(
                    409,
                    "session_terminal",
                    "Execution Session is terminal",
                    "Completed or abandoned Sessions cannot accept more events.",
                )

            now = utc_now()
            self._apply_event(row, payload, now)
            row.updated_at = now
            row.version += 1
            row.save()
            response_session = _session_response(row)

            event = SessionEvent.objects.create(
                id=uuid4(),
                session_id=row.id,
                owner_id=self.owner_id,
                type=payload.type.value,
                occurred_at=now,
                client_occurred_at=payload.client_occurred_at,
                segment_index=payload.segment_index,
                idempotency_key=idempotency_key,
                request_hash=digest,
                payload_json=payload.payload,
                result_session_snapshot_json=response_session,
                created_at=now,
            )
            return {
                "event": _event_response(event),
                "session": response_session,
            }

    def list_events(
        self,
        session_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        if self._session(session_id) is None:
            raise self._not_found(
                "execution_session_not_found",
                "Execution Session not found",
            )

        query = SessionEvent.objects.filter(
            session_id=session_id,
            owner_id=self.owner_id,
        )
        if cursor is not None:
            occurred_at, row_id = self._decode_cursor(cursor)
            query = query.filter(
                Q(occurred_at__gt=occurred_at) | Q(occurred_at=occurred_at, id__gt=row_id)
            )

        rows = list(query.order_by("occurred_at", "id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].occurred_at, rows[-1].id) if has_more and rows else None
        )
        return {
            "items": [_event_response(row) for row in rows],
            "page": {
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
        }

    def get_review(self, session_id: UUID) -> dict[str, Any]:
        if self._session(session_id) is None:
            raise self._not_found(
                "execution_session_not_found",
                "Execution Session not found",
            )
        row = SessionReview.objects.filter(
            session_id=session_id,
            owner_id=self.owner_id,
        ).first()
        if row is None:
            raise self._not_found(
                "session_review_not_found",
                "Session review not found",
            )
        return _review_response(row)

    def upsert_review(
        self,
        session_id: UUID,
        payload: UpsertSessionReviewRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_body = payload.model_dump(mode="json", by_alias=True)

        with transaction.atomic():
            session = self._session(session_id, lock=True)
            if session is None:
                raise self._not_found(
                    "execution_session_not_found",
                    "Execution Session not found",
                )
            if session.state not in {
                ExecutionSessionState.COMPLETED.value,
                ExecutionSessionState.ABANDONED.value,
            }:
                raise TaskillerAPIError(
                    409,
                    "session_review_before_terminal",
                    "Session is still open",
                    "A review can be saved after the Session is completed or abandoned.",
                )

            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope=f"execution-sessions:{session_id}:review",
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            now = utc_now()
            row = (
                SessionReview.objects.select_for_update()
                .filter(
                    session_id=session_id,
                    owner_id=self.owner_id,
                )
                .first()
            )
            if row is None:
                row = SessionReview(
                    session_id=session_id,
                    owner_id=self.owner_id,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            else:
                row.updated_at = now
                row.version += 1

            row.focus_score = payload.focus_score
            row.fatigue_score = payload.fatigue_score
            row.difficulty_score = payload.difficulty_score
            row.satisfaction_score = payload.satisfaction_score
            row.note = payload.note.strip() if payload.note is not None else None
            row.save()

            response = _review_response(row)
            complete_idempotency(
                owner_id=self.owner_id,
                scope=f"execution-sessions:{session_id}:review",
                key=idempotency_key,
                response_status=200,
                response_body=response,
                resource_id=session_id,
            )
            return response

    def _apply_event(
        self,
        row: ExecutionSession,
        payload: CreateSessionEventRequest,
        now: datetime,
    ) -> None:
        event_type = payload.type
        if event_type is SessionEventType.PAUSED:
            self._require_state(row, ExecutionSessionState.RUNNING)
            row.state = ExecutionSessionState.PAUSED.value
            row.paused_at = now
            return

        if event_type is SessionEventType.RESUMED:
            self._require_state(row, ExecutionSessionState.PAUSED)
            if row.paused_at is not None and row.current_segment_started_at is not None:
                row.current_segment_started_at += now - row.paused_at
            row.state = ExecutionSessionState.RUNNING.value
            row.paused_at = None
            return

        if event_type in {
            SessionEventType.SEGMENT_STARTED,
            SessionEventType.BREAK_STARTED,
        }:
            self._require_state(row, ExecutionSessionState.RUNNING)
            segment = self._require_current_segment(row, payload.segment_index)
            if event_type is SessionEventType.BREAK_STARTED and segment["kind"] not in _BREAK_KINDS:
                raise self._invalid_event(
                    "break_started requires the current segment to be a break"
                )
            if event_type is SessionEventType.SEGMENT_STARTED and segment["kind"] in _BREAK_KINDS:
                raise self._invalid_event("break segments must use break_started")
            if row.current_segment_started_at is not None:
                raise self._invalid_event("the current segment has already started")
            row.current_segment_started_at = now
            return

        if event_type in {
            SessionEventType.SEGMENT_COMPLETED,
            SessionEventType.SEGMENT_SKIPPED,
            SessionEventType.BREAK_ENDED,
        }:
            self._require_state(row, ExecutionSessionState.RUNNING)
            segment = self._require_current_segment(row, payload.segment_index)
            if event_type is SessionEventType.SEGMENT_SKIPPED and not bool(segment.get("optional")):
                raise self._invalid_event("only optional segments may be skipped")
            if (
                event_type is not SessionEventType.SEGMENT_SKIPPED
                and row.current_segment_started_at is None
            ):
                raise self._invalid_event("the current segment has not started")
            if event_type is SessionEventType.BREAK_ENDED and segment["kind"] not in _BREAK_KINDS:
                raise self._invalid_event("break_ended requires the current segment to be a break")
            if event_type is SessionEventType.SEGMENT_COMPLETED and segment["kind"] in _BREAK_KINDS:
                raise self._invalid_event("break segments must use break_ended")
            row.current_segment_index += 1
            row.current_segment_started_at = None
            return

        if event_type is SessionEventType.WORK_ITEM_COMPLETED:
            self._complete_work_item_for_event(row, payload, now)
            return

        if event_type is SessionEventType.SESSION_COMPLETED:
            row.state = ExecutionSessionState.COMPLETED.value
            row.paused_at = None
            row.ended_at = now
            row.current_segment_started_at = None
            return

        if event_type is SessionEventType.SESSION_ABANDONED:
            row.state = ExecutionSessionState.ABANDONED.value
            row.paused_at = None
            row.ended_at = now
            row.current_segment_started_at = None
            return

        raise self._invalid_event(f"event type {event_type.value} is not accepted here")

    def _complete_work_item_for_event(
        self,
        row: ExecutionSession,
        payload: CreateSessionEventRequest,
        now: datetime,
    ) -> None:
        raw_id = payload.payload.get("workItemId")
        target_id = row.work_item_id
        if raw_id is not None:
            try:
                target_id = UUID(str(raw_id))
            except ValueError as exc:
                raise self._invalid_event("payload.workItemId must be a UUID") from exc
        elif row.current_segment_index < len(self._plan_segments(row)):
            linked = self._plan_segments(row)[row.current_segment_index].get("linkedWorkItemId")
            if linked is not None:
                target_id = UUID(str(linked))

        session_target = self._lock_work_item(row.work_item_id)
        if session_target is None:
            raise self._invalid_event("session work item was not found")
        target = (
            session_target if target_id == session_target.id else self._lock_work_item(target_id)
        )
        if target is None:
            raise self._invalid_event("work item to complete was not found")

        if session_target.kind == WorkItemKind.CHORE.value and target.id != session_target.id:
            raise self._invalid_event("a Chore Session may only complete its own Chore")
        if session_target.kind == WorkItemKind.SPRINT.value and (
            target.kind != WorkItemKind.CHORE.value or target.parent_id != session_target.id
        ):
            raise self._invalid_event("a Sprint Session may only complete a direct child Chore")
        if target.status in {
            WorkItemStatus.CANCELLED.value,
            WorkItemStatus.ARCHIVED.value,
        }:
            raise self._invalid_event("cancelled or archived work cannot be completed")
        if target.status == WorkItemStatus.COMPLETED.value:
            return

        if target.status == WorkItemStatus.DRAFT.value:
            target.status = WorkItemStatus.READY.value
            target.updated_at = now
            target.version += 1

        target.status = WorkItemStatus.COMPLETED.value
        target.completed_at = now
        target.cancelled_at = None
        target.archived_at = None
        target.updated_at = now
        target.version += 1
        target.save()

    def _move_work_item_to_in_progress(
        self,
        row: WorkItem,
        now: datetime,
    ) -> None:
        changed = False
        if row.status == WorkItemStatus.DRAFT.value:
            row.status = WorkItemStatus.READY.value
            row.updated_at = now
            row.version += 1
            changed = True
        if row.status == WorkItemStatus.READY.value:
            row.status = WorkItemStatus.IN_PROGRESS.value
            row.updated_at = now
            row.version += 1
            changed = True
        if changed:
            row.save()

    def _lock_work_item(self, work_item_id: UUID) -> WorkItem | None:
        return (
            WorkItem.objects.select_for_update()
            .filter(
                id=work_item_id,
                owner_id=self.owner_id,
                deleted_at__isnull=True,
            )
            .first()
        )

    def _session(
        self,
        session_id: UUID,
        *,
        lock: bool = False,
    ) -> ExecutionSession | None:
        query = ExecutionSession.objects.filter(
            id=session_id,
            owner_id=self.owner_id,
        )
        if lock:
            query = query.select_for_update()
        return query.first()

    def _snapshot_work_context(
        self,
        work_item: WorkItem,
        segments: list[FocusPlanSegment],
    ) -> dict[str, object]:
        all_items = list(WorkItem.objects.filter(owner_id=self.owner_id))
        item_by_id = {item.id: item for item in all_items}
        referenced_ids = {work_item.id}
        for segment in segments:
            if segment.linked_work_item_id is not None:
                referenced_ids.add(segment.linked_work_item_id)

        work_type_ids = {
            item_by_id[item_id].work_type_id
            for item_id in referenced_ids
            if item_id in item_by_id and item_by_id[item_id].work_type_id is not None
        }
        work_types = {row.id: row for row in WorkType.objects.filter(id__in=work_type_ids)}

        def item_snapshot(item: WorkItem) -> dict[str, object]:
            ancestor_ids: list[str] = []
            seen: set[UUID] = set()
            parent_id = item.parent_id
            while parent_id is not None and parent_id not in seen:
                seen.add(parent_id)
                ancestor_ids.append(str(parent_id))
                parent = item_by_id.get(parent_id)
                if parent is None:
                    break
                parent_id = parent.parent_id
            work_type = work_types.get(item.work_type_id) if item.work_type_id is not None else None
            return {
                "id": str(item.id),
                "kind": item.kind,
                "parentId": (str(item.parent_id) if item.parent_id is not None else None),
                "ancestorIds": ancestor_ids,
                "workTypeId": (str(item.work_type_id) if item.work_type_id is not None else None),
                "workTypeSlug": (work_type.slug if work_type is not None else None),
                "estimatedEffortSeconds": item.estimated_effort_seconds,
                "plannedStartAt": (
                    item.planned_start_at.isoformat() if item.planned_start_at is not None else None
                ),
            }

        linked: dict[str, object] = {}
        for item_id in referenced_ids:
            if item_id == work_item.id:
                continue
            item = item_by_id.get(item_id)
            if item is not None:
                linked[str(item_id)] = item_snapshot(item)

        return {
            "capturedAt": utc_now().isoformat(),
            "target": item_snapshot(work_item),
            "linkedWorkItems": linked,
        }

    @staticmethod
    def _snapshot_plan(
        segments: list[FocusPlanSegment],
    ) -> FocusPlanSnapshot:
        values = [
            FocusPlanSegmentInput(
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
            for segment in segments
        ]
        return FocusPlanSnapshot(strategy=None, segments=values)

    @staticmethod
    def _plan_segments(row: ExecutionSession) -> list[dict[str, Any]]:
        raw = row.plan_snapshot_json.get("segments", [])
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _require_current_segment(
        self,
        row: ExecutionSession,
        segment_index: int | None,
    ) -> dict[str, Any]:
        segments = self._plan_segments(row)
        if row.current_segment_index >= len(segments):
            raise self._invalid_event("the Focus Plan has no current segment")
        if segment_index != row.current_segment_index:
            raise self._invalid_event(
                f"segmentIndex must equal the current segment index {row.current_segment_index}"
            )
        return segments[row.current_segment_index]

    @staticmethod
    def _require_state(
        row: ExecutionSession,
        state: ExecutionSessionState,
    ) -> None:
        if row.state != state.value:
            raise TaskillerAPIError(
                409,
                "invalid_session_transition",
                "Invalid Session transition",
                f"This event requires Session state {state.value}; current state is {row.state}.",
            )

    @staticmethod
    def _normalize_datetime_bound(
        value: datetime | None,
        name: str,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise TaskillerAPIError(
                422,
                "invalid_datetime_timezone",
                "Datetime must include a UTC offset",
                f"{name} must include a UTC offset.",
            )
        return value.astimezone(UTC)

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _encode_cursor(at: datetime, row_id: UUID) -> str:
        payload = json.dumps(
            [at.astimezone(UTC).isoformat(), str(row_id)],
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            at = datetime.fromisoformat(value[0])
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError
            return at.astimezone(UTC), UUID(value[1])
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise TaskillerAPIError(
                422,
                "invalid_cursor",
                "Invalid cursor",
            ) from exc

    @staticmethod
    def _not_found(code: str, title: str) -> TaskillerAPIError:
        return TaskillerAPIError(404, code, title)

    @staticmethod
    def _invalid_event(detail: str) -> TaskillerAPIError:
        return TaskillerAPIError(
            409,
            "invalid_session_event",
            "Invalid Session event",
            detail,
        )
