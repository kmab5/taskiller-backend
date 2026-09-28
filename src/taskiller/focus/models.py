from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from taskiller.db.base import Base


class FocusPlanRecommendationModel(Base):
    __tablename__ = "focus_plan_recommendations"
    __table_args__ = (
        CheckConstraint(
            "provenance IN ('bootstrap', 'preference_informed', 'history_informed')",
            name="ck_focus_recommendations_provenance",
        ),
        Index(
            "ix_focus_recommendations_owner_work_created",
            "owner_id",
            "work_item_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    work_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[str] = mapped_column(String(40), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    plan_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    reasons_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FocusPlanModel(Base):
    __tablename__ = "focus_plans"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'recommendation', 'template')",
            name="ck_focus_plans_source",
        ),
        CheckConstraint("version >= 1", name="ck_focus_plans_version_positive"),
        CheckConstraint(
            "(source = 'recommendation' AND recommendation_id IS NOT NULL) OR "
            "(source <> 'recommendation' AND recommendation_id IS NULL)",
            name="ck_focus_plans_recommendation_source",
        ),
        CheckConstraint(
            "(source = 'template' AND is_template) OR "
            "(source <> 'template' AND NOT is_template)",
            name="ck_focus_plans_template_source",
        ),
        CheckConstraint(
            "NOT is_template OR work_item_id IS NULL",
            name="ck_focus_plans_template_unbound",
        ),
        Index(
            "ix_focus_plans_owner_created",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_focus_plans_owner_work",
            "owner_id",
            "work_item_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_focus_plans_owner_template",
            "owner_id",
            "is_template",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    work_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE")
    )
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("focus_plan_recommendations.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    segments: Mapped[list[FocusPlanSegmentModel]] = relationship(
        back_populates="focus_plan",
        cascade="all, delete-orphan",
        order_by="FocusPlanSegmentModel.segment_index",
        lazy="selectin",
    )


class FocusPlanSegmentModel(Base):
    __tablename__ = "focus_plan_segments"
    __table_args__ = (
        UniqueConstraint("focus_plan_id", "segment_index", name="uq_focus_plan_segment_index"),
        CheckConstraint("segment_index >= 0", name="ck_focus_segments_index"),
        CheckConstraint(
            "kind IN ('work', 'break', 'long_break', 'retrieval', 'review', "
            "'planning', 'transition')",
            name="ck_focus_segments_kind",
        ),
        CheckConstraint(
            "duration_mode IN ('fixed', 'flexible', 'open')",
            name="ck_focus_segments_duration_mode",
        ),
        CheckConstraint(
            "target_seconds IS NULL OR target_seconds BETWEEN 1 AND 86400",
            name="ck_focus_segments_target",
        ),
        CheckConstraint(
            "min_seconds IS NULL OR min_seconds BETWEEN 0 AND 86400",
            name="ck_focus_segments_min",
        ),
        CheckConstraint(
            "max_seconds IS NULL OR max_seconds BETWEEN 1 AND 86400",
            name="ck_focus_segments_max",
        ),
        CheckConstraint(
            "min_seconds IS NULL OR max_seconds IS NULL OR min_seconds <= max_seconds",
            name="ck_focus_segments_range",
        ),
        CheckConstraint(
            "target_seconds IS NULL OR min_seconds IS NULL OR target_seconds >= min_seconds",
            name="ck_focus_segments_target_min",
        ),
        CheckConstraint(
            "target_seconds IS NULL OR max_seconds IS NULL OR target_seconds <= max_seconds",
            name="ck_focus_segments_target_max",
        ),
        CheckConstraint(
            "duration_mode = 'open' OR target_seconds IS NOT NULL",
            name="ck_focus_segments_target_required",
        ),
        CheckConstraint(
            "kind NOT IN ('break', 'long_break', 'transition') OR linked_work_item_id IS NULL",
            name="ck_focus_segments_nonwork_unlinked",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    focus_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("focus_plans.id", ondelete="CASCADE"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    duration_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    target_seconds: Mapped[int | None] = mapped_column(Integer)
    min_seconds: Mapped[int | None] = mapped_column(Integer)
    max_seconds: Mapped[int | None] = mapped_column(Integer)
    linked_work_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE")
    )
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(300))
    instructions: Mapped[str | None] = mapped_column(Text)

    focus_plan: Mapped[FocusPlanModel] = relationship(back_populates="segments")
