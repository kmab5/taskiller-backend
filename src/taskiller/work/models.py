from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from taskiller.db.base import Base


class WorkType(Base):
    __tablename__ = "work_types"
    __table_args__ = (
        CheckConstraint(
            "(owner_id IS NULL AND is_system) OR (owner_id IS NOT NULL AND NOT is_system)",
            name="ck_work_types_owner_system",
        ),
        CheckConstraint(
            "cognitive_demand IN ('low', 'medium', 'high')",
            name="ck_work_types_cognitive_demand",
        ),
        CheckConstraint(
            "interruption_sensitivity IN ('low', 'medium', 'high')",
            name="ck_work_types_interruption_sensitivity",
        ),
        CheckConstraint(
            "continuity_need IN ('low', 'medium', 'high')",
            name="ck_work_types_continuity_need",
        ),
        CheckConstraint(
            "repetitiveness IN ('low', 'medium', 'high')",
            name="ck_work_types_repetitiveness",
        ),
        CheckConstraint(
            "physicality IN ('sedentary', 'light', 'active')",
            name="ck_work_types_physicality",
        ),
        CheckConstraint(
            "learning_mode IN ('none', 'acquisition', 'retrieval', 'practice')",
            name="ck_work_types_learning_mode",
        ),
        CheckConstraint("version >= 1", name="ck_work_types_version_positive"),
        Index(
            "uq_work_types_system_slug",
            text("lower(slug)"),
            unique=True,
            postgresql_where=text("owner_id IS NULL"),
        ),
        Index(
            "uq_work_types_owner_slug",
            "owner_id",
            text("lower(slug)"),
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    cognitive_demand: Mapped[str] = mapped_column(String(20), nullable=False)
    interruption_sensitivity: Mapped[str] = mapped_column(String(20), nullable=False)
    continuity_need: Mapped[str] = mapped_column(String(20), nullable=False)
    repetitiveness: Mapped[str] = mapped_column(String(20), nullable=False)
    physicality: Mapped[str] = mapped_column(String(20), nullable=False)
    learning_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint("kind IN ('project', 'sprint', 'chore')", name="ck_work_items_kind"),
        CheckConstraint(
            "status IN ('draft', 'ready', 'in_progress', 'completed', 'cancelled', 'archived')",
            name="ck_work_items_status",
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 300", name="ck_work_items_name"),
        CheckConstraint(
            "priority IS NULL OR priority BETWEEN 0 AND 5",
            name="ck_work_items_priority",
        ),
        CheckConstraint(
            "estimated_effort_seconds IS NULL OR "
            "estimated_effort_seconds BETWEEN 0 AND 31536000",
            name="ck_work_items_estimate",
        ),
        CheckConstraint(
            "planned_start_at IS NULL OR deadline_at IS NULL OR planned_start_at <= deadline_at",
            name="ck_work_items_planned_range",
        ),
        CheckConstraint(
            "target_start_date IS NULL OR target_end_date IS NULL OR "
            "target_start_date <= target_end_date",
            name="ck_work_items_target_range",
        ),
        CheckConstraint(
            "kind = 'project' OR (target_start_date IS NULL AND target_end_date IS NULL)",
            name="ck_work_items_project_dates",
        ),
        CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="ck_work_items_completed_timestamp",
        ),
        CheckConstraint(
            "status <> 'cancelled' OR cancelled_at IS NOT NULL",
            name="ck_work_items_cancelled_timestamp",
        ),
        CheckConstraint(
            "status <> 'archived' OR archived_at IS NOT NULL",
            name="ck_work_items_archived_timestamp",
        ),
        CheckConstraint("version >= 1", name="ck_work_items_version_positive"),
        CheckConstraint(
            "cognitive_demand_override IS NULL OR "
            "cognitive_demand_override IN ('low', 'medium', 'high')",
            name="ck_work_items_cognitive_override",
        ),
        CheckConstraint(
            "interruption_sensitivity_override IS NULL OR "
            "interruption_sensitivity_override IN ('low', 'medium', 'high')",
            name="ck_work_items_interruption_override",
        ),
        CheckConstraint(
            "continuity_need_override IS NULL OR "
            "continuity_need_override IN ('low', 'medium', 'high')",
            name="ck_work_items_continuity_override",
        ),
        CheckConstraint(
            "repetitiveness_override IS NULL OR "
            "repetitiveness_override IN ('low', 'medium', 'high')",
            name="ck_work_items_repetitiveness_override",
        ),
        CheckConstraint(
            "physicality_override IS NULL OR "
            "physicality_override IN ('sedentary', 'light', 'active')",
            name="ck_work_items_physicality_override",
        ),
        CheckConstraint(
            "learning_mode_override IS NULL OR "
            "learning_mode_override IN ('none', 'acquisition', 'retrieval', 'practice')",
            name="ck_work_items_learning_override",
        ),
        Index(
            "ix_work_items_owner_status_kind",
            "owner_id",
            "status",
            "kind",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_work_items_owner_parent_position",
            "owner_id",
            "parent_id",
            "position",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_work_items_owner_created",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_work_items_owner_deadline",
            "owner_id",
            "deadline_at",
            postgresql_where=text("deleted_at IS NULL AND deadline_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT")
    )
    work_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_types.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    position: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1024)
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    estimated_effort_seconds: Mapped[int | None] = mapped_column(Integer)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_start_date: Mapped[date | None] = mapped_column(Date)
    target_end_date: Mapped[date | None] = mapped_column(Date)
    cognitive_demand_override: Mapped[str | None] = mapped_column(String(20))
    interruption_sensitivity_override: Mapped[str | None] = mapped_column(String(20))
    continuity_need_override: Mapped[str | None] = mapped_column(String(20))
    repetitiveness_override: Mapped[str | None] = mapped_column(String(20))
    physicality_override: Mapped[str | None] = mapped_column(String(20))
    learning_mode_override: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
