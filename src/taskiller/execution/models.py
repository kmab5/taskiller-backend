from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from taskiller.db.base import Base


class ExecutionSessionModel(Base):
    __tablename__ = "execution_sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('running', 'paused', 'completed', 'abandoned')",
            name="ck_execution_sessions_state",
        ),
        CheckConstraint(
            "current_segment_index >= 0", name="ck_execution_sessions_segment_index"
        ),
        CheckConstraint("version >= 1", name="ck_execution_sessions_version_positive"),
        CheckConstraint(
            "(state IN ('completed', 'abandoned') AND ended_at IS NOT NULL) OR "
            "(state IN ('running', 'paused') AND ended_at IS NULL)",
            name="ck_execution_sessions_end_state",
        ),
        CheckConstraint(
            "(state = 'paused' AND paused_at IS NOT NULL) OR "
            "(state <> 'paused' AND paused_at IS NULL)",
            name="ck_execution_sessions_pause_state",
        ),
        Index(
            "uq_execution_sessions_one_open_per_user",
            "owner_id",
            unique=True,
            postgresql_where=text("state IN ('running', 'paused')"),
        ),
        Index(
            "ix_execution_sessions_owner_started",
            "owner_id",
            text("session_started_at DESC"),
        ),
        Index(
            "ix_execution_sessions_work_item_started",
            "work_item_id",
            text("session_started_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    work_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False
    )
    focus_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("focus_plans.id", ondelete="RESTRICT"), nullable=False
    )
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("focus_plan_recommendations.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    current_segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    session_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_segment_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    recommendation_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    work_context_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SessionEventModel(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_session_events_idempotency"),
        CheckConstraint(
            "type IN ('session_started', 'paused', 'resumed', 'segment_started', "
            "'segment_completed', 'segment_skipped', 'break_started', 'break_ended', "
            "'work_item_completed', 'session_completed', 'session_abandoned')",
            name="ck_session_events_type",
        ),
        CheckConstraint(
            "segment_index IS NULL OR segment_index >= 0", name="ck_session_events_segment_index"
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 200",
            name="ck_session_events_idempotency_length",
        ),
        Index("ix_session_events_session_time", "session_id", "occurred_at", "id"),
        Index("ix_session_events_owner_time", "owner_id", text("occurred_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_sessions.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    segment_index: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    result_session_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionReviewModel(Base):
    __tablename__ = "session_reviews"
    __table_args__ = (
        CheckConstraint(
            "focus_score IS NULL OR focus_score BETWEEN 1 AND 5",
            name="ck_session_reviews_focus",
        ),
        CheckConstraint(
            "fatigue_score IS NULL OR fatigue_score BETWEEN 1 AND 5",
            name="ck_session_reviews_fatigue",
        ),
        CheckConstraint(
            "difficulty_score IS NULL OR difficulty_score BETWEEN 1 AND 5",
            name="ck_session_reviews_difficulty",
        ),
        CheckConstraint(
            "satisfaction_score IS NULL OR satisfaction_score BETWEEN 1 AND 5",
            name="ck_session_reviews_satisfaction",
        ),
        CheckConstraint(
            "note IS NULL OR char_length(note) <= 4000", name="ck_session_reviews_note_length"
        ),
        CheckConstraint("version >= 1", name="ck_session_reviews_version_positive"),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    focus_score: Mapped[int | None] = mapped_column(SmallInteger)
    fatigue_score: Mapped[int | None] = mapped_column(SmallInteger)
    difficulty_score: Mapped[int | None] = mapped_column(SmallInteger)
    satisfaction_score: Mapped[int | None] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
