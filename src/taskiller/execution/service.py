from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from taskiller.core.idempotency import claim_idempotency, complete_idempotency
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import User
from taskiller.execution.models import (
    ExecutionSessionModel,
    SessionEventModel,
    SessionReviewModel,
)
from taskiller.execution.presenters import (
    execution_session_to_response,
    session_event_to_response,
    session_review_to_response,
)
from taskiller.execution.schemas import (
    ActiveExecutionSession,
    AppendSessionEventResponse,
    CreateSessionEventRequest,
    ExecutionSession,
    ExecutionSessionPage,
    ExecutionSessionState,
    PageMeta,
    SessionEventPage,
    SessionEventType,
    SessionReview,
    StartExecutionSessionRequest,
    UpsertSessionReviewRequest,
)
from taskiller.focus.models import (
    FocusPlanModel,
    FocusPlanRecommendationModel,
)
from taskiller.focus.schemas import FocusPlanSnapshot, FocusPlanSegmentInput, FocusSegmentKind
from taskiller.users.etag import make_etag, require_etag
from taskiller.work.models import WorkItem, WorkType
from taskiller.work.schemas import WorkItemKind, WorkItemStatus

_TERMINAL_WORK_STATES = {
    WorkItemStatus.COMPLETED.value,
    WorkItemStatus.CANCELLED.value,
    WorkItemStatus.ARCHIVED.value,
}
_BREAK_KINDS = {FocusSegmentKind.BREAK.value, FocusSegmentKind.LONG_BREAK.value}


class ExecutionService:
    def __init__(self, db: AsyncSession, owner_id: UUID, idempotency_ttl_hours: int) -> None:
        self.db = db
        self.owner_id = owner_id
        self.idempotency_ttl_hours = idempotency_ttl_hours

    async def start_session(
        self,
        payload: StartExecutionSessionRequest,
        idempotency_key: str,
    ) -> ExecutionSession:
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="execution-sessions:start",
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return ExecutionSession.model_validate(replay.response_body)

        await self._lock_owner()
        work_item = await self._lock_work_item(payload.work_item_id)
        if work_item is None:
            raise self._not_found("work_item_not_found", "Work item not found")
        if work_item.kind not in {WorkItemKind.CHORE.value, WorkItemKind.SPRINT.value}:
            raise ApiError(
                422,
                "project_not_executable",
                "Projects cannot be executed directly",
                "Resolve the Project to a Chore or Sprint before starting a Session.",
            )
        if work_item.status in _TERMINAL_WORK_STATES:
            raise ApiError(
                409,
                "work_item_terminal",
                "Work item is terminal",
                "Completed, cancelled, or archived work cannot start a new Session.",
            )

        focus_plan = await self.db.scalar(
            select(FocusPlanModel)
            .options(selectinload(FocusPlanModel.segments))
            .where(
                FocusPlanModel.id == payload.focus_plan_id,
                FocusPlanModel.owner_id == self.owner_id,
                FocusPlanModel.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if focus_plan is None:
            raise self._not_found("focus_plan_not_found", "Focus Plan not found")
        if focus_plan.is_template:
            raise ApiError(
                422,
                "focus_plan_template_unexecutable",
                "Template cannot be executed directly",
                "Create a non-template Focus Plan before starting a Session.",
            )
        if focus_plan.work_item_id != work_item.id:
            raise ApiError(
                422,
                "focus_plan_work_item_mismatch",
                "Focus Plan does not match work item",
                "The selected Focus Plan must be bound to the Session work item.",
            )
        if not focus_plan.segments:
            raise ApiError(422, "empty_focus_plan", "Focus Plan has no segments")

        recommendation_id = payload.recommendation_id or focus_plan.recommendation_id
        recommendation_snapshot: dict[str, object] | None = None
        if recommendation_id is not None:
            recommendation = await self.db.scalar(
                select(FocusPlanRecommendationModel).where(
                    FocusPlanRecommendationModel.id == recommendation_id,
                    FocusPlanRecommendationModel.owner_id == self.owner_id,
                )
            )
            if recommendation is None:
                raise self._not_found("recommendation_not_found", "Recommendation not found")
            if recommendation.work_item_id != work_item.id:
                raise ApiError(
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

        plan_snapshot = self._snapshot_plan(focus_plan)
        work_context_snapshot = await self._snapshot_work_context(work_item, focus_plan)
        now = utc_now()
        row = ExecutionSessionModel(
            id=uuid4(),
            owner_id=self.owner_id,
            work_item_id=work_item.id,
            focus_plan_id=focus_plan.id,
            recommendation_id=recommendation_id,
            state=ExecutionSessionState.RUNNING.value,
            current_segment_index=0,
            session_started_at=now,
            current_segment_started_at=now,
            paused_at=None,
            ended_at=None,
            plan_snapshot_json=plan_snapshot.model_dump(mode="json", by_alias=True),
            recommendation_snapshot_json=recommendation_snapshot,
            work_context_snapshot_json=work_context_snapshot,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            if "uq_execution_sessions_one_open_per_user" not in str(exc.orig):
                raise
            raise ApiError(
                409,
                "open_session_exists",
                "Another Session is already open",
                "Complete or abandon the existing Session before starting another.",
            ) from exc

        await self._move_work_item_to_in_progress(work_item, now)
        start_event = SessionEventModel(
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
            result_session_snapshot_json={},
            created_at=now,
        )
        initial_kind = plan_snapshot.segments[0].kind
        initial_type = (
            SessionEventType.BREAK_STARTED
            if initial_kind.value in _BREAK_KINDS
            else SessionEventType.SEGMENT_STARTED
        )
        initial_event = SessionEventModel(
            id=uuid4(),
            session_id=row.id,
            owner_id=self.owner_id,
            type=initial_type.value,
            occurred_at=now,
            client_occurred_at=None,
            segment_index=0,
            idempotency_key=f"initial:{idempotency_key}"[:200],
            request_hash=self._hash_payload(
                {"type": initial_type.value, "segmentIndex": 0}
            ),
            payload_json={},
            result_session_snapshot_json={},
            created_at=now,
        )
        self.db.add_all([start_event, initial_event])
        await self.db.flush()
        response = execution_session_to_response(row)
        snapshot = response.model_dump(mode="json", by_alias=True)
        start_event.result_session_snapshot_json = snapshot
        initial_event.result_session_snapshot_json = snapshot
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="execution-sessions:start",
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_active_session(self) -> ActiveExecutionSession:
        row = await self.db.scalar(
            select(ExecutionSessionModel)
            .where(
                ExecutionSessionModel.owner_id == self.owner_id,
                ExecutionSessionModel.state.in_(
                    [ExecutionSessionState.RUNNING.value, ExecutionSessionState.PAUSED.value]
                ),
            )
            .order_by(ExecutionSessionModel.session_started_at.desc())
        )
        return ActiveExecutionSession(
            session=execution_session_to_response(row) if row is not None else None
        )

    async def get_session(self, session_id: UUID) -> ExecutionSession:
        row = await self._session(session_id)
        if row is None:
            raise self._not_found("execution_session_not_found", "Execution Session not found")
        return execution_session_to_response(row)

    async def list_sessions(
        self,
        *,
        limit: int,
        cursor: str | None,
        work_item_id: UUID | None,
        state: ExecutionSessionState | None,
        from_at: datetime | None,
        to_at: datetime | None,
    ) -> ExecutionSessionPage:
        from_at = self._normalize_datetime_bound(from_at, "from")
        to_at = self._normalize_datetime_bound(to_at, "to")
        if from_at is not None and to_at is not None and from_at >= to_at:
            raise ApiError(
                422, "invalid_time_range", "Invalid time range", "from must be before to."
            )
        stmt = (
            select(ExecutionSessionModel)
            .where(ExecutionSessionModel.owner_id == self.owner_id)
            .order_by(
                ExecutionSessionModel.session_started_at.desc(),
                ExecutionSessionModel.id.desc(),
            )
            .limit(limit + 1)
        )
        if work_item_id is not None:
            stmt = stmt.where(ExecutionSessionModel.work_item_id == work_item_id)
        if state is not None:
            stmt = stmt.where(ExecutionSessionModel.state == state.value)
        if from_at is not None:
            stmt = stmt.where(ExecutionSessionModel.session_started_at >= from_at)
        if to_at is not None:
            stmt = stmt.where(ExecutionSessionModel.session_started_at < to_at)
        if cursor is not None:
            started_at, row_id = self._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    ExecutionSessionModel.session_started_at < started_at,
                    and_(
                        ExecutionSessionModel.session_started_at == started_at,
                        ExecutionSessionModel.id < row_id,
                    ),
                )
            )
        rows = list((await self.db.scalars(stmt)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].session_started_at, rows[-1].id)
            if has_more and rows
            else None
        )
        return ExecutionSessionPage(
            items=[execution_session_to_response(row) for row in rows],
            page=PageMeta(has_more=has_more, next_cursor=next_cursor),
        )

    async def append_event(
        self,
        session_id: UUID,
        payload: CreateSessionEventRequest,
        idempotency_key: str,
        if_match: str | None,
    ) -> AppendSessionEventResponse:
        await self._lock_owner()
        row = await self._session(session_id, lock=True)
        if row is None:
            raise self._not_found("execution_session_not_found", "Execution Session not found")
        expected_etag = make_etag("execution-session", row.id, row.version)

        digest = self._hash_payload(payload.model_dump(mode="json", by_alias=True))
        existing = await self.db.scalar(
            select(SessionEventModel).where(
                SessionEventModel.session_id == row.id,
                SessionEventModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != digest:
                raise ApiError(
                    409,
                    "idempotency_key_reused",
                    "Idempotency key reused",
                    "The same Idempotency-Key was already used with a different event.",
                )
            return AppendSessionEventResponse(
                event=session_event_to_response(existing),
                session=ExecutionSession.model_validate(existing.result_session_snapshot_json),
            )

        require_etag(if_match, expected_etag)
        if row.state in {
            ExecutionSessionState.COMPLETED.value,
            ExecutionSessionState.ABANDONED.value,
        }:
            raise ApiError(
                409,
                "session_terminal",
                "Execution Session is terminal",
                "Completed or abandoned Sessions cannot accept more events.",
            )

        now = utc_now()
        await self._apply_event(row, payload, now)
        row.updated_at = now
        row.version += 1
        await self.db.flush()
        response_session = execution_session_to_response(row)
        event = SessionEventModel(
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
            result_session_snapshot_json=response_session.model_dump(
                mode="json", by_alias=True
            ),
            created_at=now,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.commit()
        return AppendSessionEventResponse(
            event=session_event_to_response(event),
            session=response_session,
        )

    async def list_events(
        self, session_id: UUID, *, limit: int, cursor: str | None
    ) -> SessionEventPage:
        if await self._session(session_id) is None:
            raise self._not_found("execution_session_not_found", "Execution Session not found")
        stmt = (
            select(SessionEventModel)
            .where(
                SessionEventModel.session_id == session_id,
                SessionEventModel.owner_id == self.owner_id,
            )
            .order_by(SessionEventModel.occurred_at, SessionEventModel.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            occurred_at, row_id = self._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    SessionEventModel.occurred_at > occurred_at,
                    and_(
                        SessionEventModel.occurred_at == occurred_at,
                        SessionEventModel.id > row_id,
                    ),
                )
            )
        rows = list((await self.db.scalars(stmt)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].occurred_at, rows[-1].id)
            if has_more and rows
            else None
        )
        return SessionEventPage(
            items=[session_event_to_response(row) for row in rows],
            page=PageMeta(has_more=has_more, next_cursor=next_cursor),
        )

    async def get_review(self, session_id: UUID) -> SessionReview:
        if await self._session(session_id) is None:
            raise self._not_found("execution_session_not_found", "Execution Session not found")
        row = await self.db.scalar(
            select(SessionReviewModel).where(
                SessionReviewModel.session_id == session_id,
                SessionReviewModel.owner_id == self.owner_id,
            )
        )
        if row is None:
            raise self._not_found("session_review_not_found", "Session review not found")
        return session_review_to_response(row)

    async def upsert_review(
        self,
        session_id: UUID,
        payload: UpsertSessionReviewRequest,
        idempotency_key: str,
    ) -> SessionReview:
        session = await self._session(session_id, lock=True)
        if session is None:
            raise self._not_found("execution_session_not_found", "Execution Session not found")
        if session.state not in {
            ExecutionSessionState.COMPLETED.value,
            ExecutionSessionState.ABANDONED.value,
        }:
            raise ApiError(
                409,
                "session_review_before_terminal",
                "Session is still open",
                "A review can be saved after the Session is completed or abandoned.",
            )
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=f"execution-sessions:{session_id}:review",
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return SessionReview.model_validate(replay.response_body)

        now = utc_now()
        row = await self.db.scalar(
            select(SessionReviewModel)
            .where(
                SessionReviewModel.session_id == session_id,
                SessionReviewModel.owner_id == self.owner_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            row = SessionReviewModel(
                session_id=session_id,
                owner_id=self.owner_id,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self.db.add(row)
        else:
            row.updated_at = now
            row.version += 1
        row.focus_score = payload.focus_score
        row.fatigue_score = payload.fatigue_score
        row.difficulty_score = payload.difficulty_score
        row.satisfaction_score = payload.satisfaction_score
        row.note = payload.note.strip() if payload.note is not None else None
        await self.db.flush()
        response = session_review_to_response(row)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=f"execution-sessions:{session_id}:review",
            key=idempotency_key,
            response_status=200,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=session_id,
        )
        await self.db.commit()
        return response

    async def _apply_event(
        self,
        row: ExecutionSessionModel,
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
            if (
                event_type is SessionEventType.SEGMENT_SKIPPED
                and not bool(segment.get("optional"))
            ):
                raise self._invalid_event("only optional segments may be skipped")
            if (
                event_type is not SessionEventType.SEGMENT_SKIPPED
                and row.current_segment_started_at is None
            ):
                raise self._invalid_event("the current segment has not started")
            if event_type is SessionEventType.BREAK_ENDED and segment["kind"] not in _BREAK_KINDS:
                raise self._invalid_event("break_ended requires the current segment to be a break")
            if (
                event_type is SessionEventType.SEGMENT_COMPLETED
                and segment["kind"] in _BREAK_KINDS
            ):
                raise self._invalid_event("break segments must use break_ended")
            self._advance_segment(row)
            return
        if event_type is SessionEventType.WORK_ITEM_COMPLETED:
            await self._complete_work_item_for_event(row, payload, now)
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

    async def _complete_work_item_for_event(
        self,
        row: ExecutionSessionModel,
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
        session_target = await self._lock_work_item(row.work_item_id)
        if session_target is None:
            raise self._invalid_event("session work item was not found")
        target = (
            session_target
            if target_id == session_target.id
            else await self._lock_work_item(target_id)
        )
        if target is None:
            raise self._invalid_event("work item to complete was not found")
        if session_target.kind == WorkItemKind.CHORE.value and target.id != session_target.id:
            raise self._invalid_event("a Chore Session may only complete its own Chore")
        if (
            session_target.kind == WorkItemKind.SPRINT.value
            and (target.kind != WorkItemKind.CHORE.value or target.parent_id != session_target.id)
        ):
            raise self._invalid_event("a Sprint Session may only complete a direct child Chore")
        if target.status in {WorkItemStatus.CANCELLED.value, WorkItemStatus.ARCHIVED.value}:
            raise self._invalid_event("cancelled or archived work cannot be completed")
        if target.status == WorkItemStatus.COMPLETED.value:
            return
        if target.status == WorkItemStatus.DRAFT.value:
            target.status = WorkItemStatus.READY.value
            target.updated_at = now
            target.version += 1
            await self.db.flush()
        target.status = WorkItemStatus.COMPLETED.value
        target.completed_at = now
        target.cancelled_at = None
        target.archived_at = None
        target.updated_at = now
        target.version += 1
        await self.db.flush()

    async def _move_work_item_to_in_progress(self, row: WorkItem, now: datetime) -> None:
        if row.status == WorkItemStatus.DRAFT.value:
            row.status = WorkItemStatus.READY.value
            row.updated_at = now
            row.version += 1
            await self.db.flush()
        if row.status == WorkItemStatus.READY.value:
            row.status = WorkItemStatus.IN_PROGRESS.value
            row.updated_at = now
            row.version += 1
            await self.db.flush()

    async def _lock_owner(self) -> None:
        await self.db.scalar(
            select(User.id)
            .where(User.id == self.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _lock_work_item(self, work_item_id: UUID) -> WorkItem | None:
        return await self.db.scalar(
            select(WorkItem)
            .where(
                WorkItem.id == work_item_id,
                WorkItem.owner_id == self.owner_id,
                WorkItem.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _session(
        self, session_id: UUID, *, lock: bool = False
    ) -> ExecutionSessionModel | None:
        stmt = select(ExecutionSessionModel).where(
            ExecutionSessionModel.id == session_id,
            ExecutionSessionModel.owner_id == self.owner_id,
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(stmt)

    async def _snapshot_work_context(
        self, work_item: WorkItem, focus_plan: FocusPlanModel
    ) -> dict[str, object]:
        all_items = list(
            (
                await self.db.scalars(
                    select(WorkItem).where(WorkItem.owner_id == self.owner_id)
                )
            ).all()
        )
        item_by_id = {item.id: item for item in all_items}
        referenced_ids = {work_item.id}
        for segment in focus_plan.segments:
            if segment.linked_work_item_id is not None:
                referenced_ids.add(segment.linked_work_item_id)

        work_type_ids: set[UUID] = set()
        for item_id in referenced_ids:
            item = item_by_id.get(item_id)
            if item is not None and item.work_type_id is not None:
                work_type_ids.add(item.work_type_id)
        work_types: dict[UUID, WorkType] = {}
        if work_type_ids:
            rows = list(
                (
                    await self.db.scalars(
                        select(WorkType).where(WorkType.id.in_(work_type_ids))
                    )
                ).all()
            )
            work_types = {row.id: row for row in rows}

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
            work_type = (
                work_types.get(item.work_type_id)
                if item.work_type_id is not None
                else None
            )
            return {
                "id": str(item.id),
                "kind": item.kind,
                "parentId": str(item.parent_id) if item.parent_id is not None else None,
                "ancestorIds": ancestor_ids,
                "workTypeId": str(item.work_type_id) if item.work_type_id is not None else None,
                "workTypeSlug": work_type.slug if work_type is not None else None,
                "estimatedEffortSeconds": item.estimated_effort_seconds,
                "plannedStartAt": (
                    item.planned_start_at.isoformat()
                    if item.planned_start_at is not None
                    else None
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
    def _snapshot_plan(focus_plan: FocusPlanModel) -> FocusPlanSnapshot:
        segments = [
            FocusPlanSegmentInput(
                kind=segment.kind,
                duration_mode=segment.duration_mode,
                target_seconds=segment.target_seconds,
                min_seconds=segment.min_seconds,
                max_seconds=segment.max_seconds,
                linked_work_item_id=segment.linked_work_item_id,
                optional=segment.optional,
                label=segment.label,
                instructions=segment.instructions,
            )
            for segment in focus_plan.segments
        ]
        return FocusPlanSnapshot(strategy=None, segments=segments)

    @staticmethod
    def _plan_segments(row: ExecutionSessionModel) -> list[dict[str, Any]]:
        raw = cast(list[object], row.plan_snapshot_json.get("segments", []))
        return [dict(cast(dict[str, Any], item)) for item in raw if isinstance(item, dict)]

    def _require_current_segment(
        self, row: ExecutionSessionModel, segment_index: int | None
    ) -> dict[str, Any]:
        segments = self._plan_segments(row)
        if row.current_segment_index >= len(segments):
            raise self._invalid_event("the Focus Plan has no current segment")
        if segment_index != row.current_segment_index:
            raise self._invalid_event(
                f"segmentIndex must equal the current segment index {row.current_segment_index}"
            )
        return segments[row.current_segment_index]

    def _advance_segment(self, row: ExecutionSessionModel) -> None:
        row.current_segment_index += 1
        row.current_segment_started_at = None

    @staticmethod
    def _require_state(row: ExecutionSessionModel, state: ExecutionSessionState) -> None:
        if row.state != state.value:
            raise ApiError(
                409,
                "invalid_session_transition",
                "Invalid Session transition",
                f"This event requires Session state {state.value}; current state is {row.state}.",
            )

    @staticmethod
    def _normalize_datetime_bound(value: datetime | None, name: str) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ApiError(
                422,
                "invalid_datetime_timezone",
                "Datetime must include a UTC offset",
                f"{name} must include a UTC offset.",
            )
        return value.astimezone(UTC)

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _encode_cursor(at: datetime, row_id: UUID) -> str:
        payload = json.dumps([at.astimezone(UTC).isoformat(), str(row_id)], separators=(",", ":"))
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
            raise ApiError(400, "invalid_cursor", "Invalid cursor") from exc

    @staticmethod
    def _not_found(code: str, title: str) -> ApiError:
        return ApiError(404, code, title)

    @staticmethod
    def _invalid_event(detail: str) -> ApiError:
        return ApiError(409, "invalid_session_event", "Invalid Session event", detail)
