from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from taskiller.api.models import ApiModel
from taskiller.focus.schemas import FocusPlanSnapshot


class ExecutionSessionState(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class SessionEventType(StrEnum):
    SESSION_STARTED = "session_started"
    PAUSED = "paused"
    RESUMED = "resumed"
    SEGMENT_STARTED = "segment_started"
    SEGMENT_COMPLETED = "segment_completed"
    SEGMENT_SKIPPED = "segment_skipped"
    BREAK_STARTED = "break_started"
    BREAK_ENDED = "break_ended"
    WORK_ITEM_COMPLETED = "work_item_completed"
    SESSION_COMPLETED = "session_completed"
    SESSION_ABANDONED = "session_abandoned"


class StartExecutionSessionRequest(ApiModel):
    work_item_id: UUID
    focus_plan_id: UUID
    recommendation_id: UUID | None = None


class ExecutionSession(ApiModel):
    id: UUID
    work_item_id: UUID
    focus_plan_id: UUID
    recommendation_id: UUID | None
    state: ExecutionSessionState
    current_segment_index: int = Field(ge=0)
    session_started_at: datetime
    current_segment_started_at: datetime | None
    paused_at: datetime | None
    ended_at: datetime | None
    plan_snapshot: FocusPlanSnapshot
    recommendation_snapshot: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class ActiveExecutionSession(ApiModel):
    session: ExecutionSession | None


class PageMeta(ApiModel):
    has_more: bool
    next_cursor: str | None


class ExecutionSessionPage(ApiModel):
    items: list[ExecutionSession]
    page: PageMeta


class CreateSessionEventRequest(ApiModel):
    type: SessionEventType
    segment_index: int | None = Field(default=None, ge=0)
    client_occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("client_occurred_at")
    @classmethod
    def normalize_client_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clientOccurredAt must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.type is SessionEventType.SESSION_STARTED:
            raise ValueError("session_started is created by the session start endpoint")
        if (
            self.type
            in {
                SessionEventType.SEGMENT_STARTED,
                SessionEventType.SEGMENT_COMPLETED,
                SessionEventType.SEGMENT_SKIPPED,
                SessionEventType.BREAK_STARTED,
                SessionEventType.BREAK_ENDED,
            }
            and self.segment_index is None
        ):
            raise ValueError("segmentIndex is required for segment and break events")
        if (
            self.type
            not in {
                SessionEventType.SEGMENT_STARTED,
                SessionEventType.SEGMENT_COMPLETED,
                SessionEventType.SEGMENT_SKIPPED,
                SessionEventType.BREAK_STARTED,
                SessionEventType.BREAK_ENDED,
            }
            and self.segment_index is not None
        ):
            raise ValueError("segmentIndex is only valid for segment and break events")
        return self


class SessionEvent(ApiModel):
    id: UUID
    session_id: UUID
    type: SessionEventType
    occurred_at: datetime
    client_occurred_at: datetime | None
    segment_index: int | None
    payload: dict[str, Any]


class SessionEventPage(ApiModel):
    items: list[SessionEvent]
    page: PageMeta


class AppendSessionEventResponse(ApiModel):
    event: SessionEvent
    session: ExecutionSession


class UpsertSessionReviewRequest(ApiModel):
    focus_score: int | None = Field(default=None, ge=1, le=5)
    fatigue_score: int | None = Field(default=None, ge=1, le=5)
    difficulty_score: int | None = Field(default=None, ge=1, le=5)
    satisfaction_score: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=4000)


class SessionReview(UpsertSessionReviewRequest):
    session_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)
