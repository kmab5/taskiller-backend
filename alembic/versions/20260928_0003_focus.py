"""focus plans and deterministic recommendations

Revision ID: 20260928_0003
Revises: 20260928_0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0003"
down_revision: str | None = "20260928_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focus_plan_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("provenance", sa.String(length=40), nullable=False),
        sa.Column("strategy", sa.String(length=40), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("plan_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('bootstrap', 'preference_informed', 'history_informed')",
            name="ck_focus_recommendations_provenance",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_focus_recommendations_owner_work_created",
        "focus_plan_recommendations",
        ["owner_id", "work_item_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "focus_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=True),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_template", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source IN ('manual', 'recommendation', 'template')",
            name="ck_focus_plans_source",
        ),
        sa.CheckConstraint("version >= 1", name="ck_focus_plans_version_positive"),
        sa.CheckConstraint(
            "(source = 'recommendation' AND recommendation_id IS NOT NULL) OR "
            "(source <> 'recommendation' AND recommendation_id IS NULL)",
            name="ck_focus_plans_recommendation_source",
        ),
        sa.CheckConstraint(
            "(source = 'template' AND is_template) OR (source <> 'template' AND NOT is_template)",
            name="ck_focus_plans_template_source",
        ),
        sa.CheckConstraint(
            "NOT is_template OR work_item_id IS NULL",
            name="ck_focus_plans_template_unbound",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["focus_plan_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_focus_plans_owner_created",
        "focus_plans",
        ["owner_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_focus_plans_owner_work",
        "focus_plans",
        ["owner_id", "work_item_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_focus_plans_owner_template",
        "focus_plans",
        ["owner_id", "is_template"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "focus_plan_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("focus_plan_id", sa.Uuid(), nullable=False),
        sa.Column("segment_index", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("duration_mode", sa.String(length=20), nullable=False),
        sa.Column("target_seconds", sa.Integer(), nullable=True),
        sa.Column("min_seconds", sa.Integer(), nullable=True),
        sa.Column("max_seconds", sa.Integer(), nullable=True),
        sa.Column("linked_work_item_id", sa.Uuid(), nullable=True),
        sa.Column("optional", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.CheckConstraint("segment_index >= 0", name="ck_focus_segments_index"),
        sa.CheckConstraint(
            "kind IN ('work', 'break', 'long_break', 'retrieval', 'review', "
            "'planning', 'transition')",
            name="ck_focus_segments_kind",
        ),
        sa.CheckConstraint(
            "duration_mode IN ('fixed', 'flexible', 'open')",
            name="ck_focus_segments_duration_mode",
        ),
        sa.CheckConstraint(
            "target_seconds IS NULL OR target_seconds BETWEEN 1 AND 86400",
            name="ck_focus_segments_target",
        ),
        sa.CheckConstraint(
            "min_seconds IS NULL OR min_seconds BETWEEN 0 AND 86400",
            name="ck_focus_segments_min",
        ),
        sa.CheckConstraint(
            "max_seconds IS NULL OR max_seconds BETWEEN 1 AND 86400",
            name="ck_focus_segments_max",
        ),
        sa.CheckConstraint(
            "min_seconds IS NULL OR max_seconds IS NULL OR min_seconds <= max_seconds",
            name="ck_focus_segments_range",
        ),
        sa.CheckConstraint(
            "target_seconds IS NULL OR min_seconds IS NULL OR target_seconds >= min_seconds",
            name="ck_focus_segments_target_min",
        ),
        sa.CheckConstraint(
            "target_seconds IS NULL OR max_seconds IS NULL OR target_seconds <= max_seconds",
            name="ck_focus_segments_target_max",
        ),
        sa.CheckConstraint(
            "duration_mode = 'open' OR target_seconds IS NOT NULL",
            name="ck_focus_segments_target_required",
        ),
        sa.CheckConstraint(
            "kind NOT IN ('break', 'long_break', 'transition') OR linked_work_item_id IS NULL",
            name="ck_focus_segments_nonwork_unlinked",
        ),
        sa.ForeignKeyConstraint(["focus_plan_id"], ["focus_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("focus_plan_id", "segment_index", name="uq_focus_plan_segment_index"),
    )


def downgrade() -> None:
    op.drop_table("focus_plan_segments")
    op.drop_index("ix_focus_plans_owner_template", table_name="focus_plans")
    op.drop_index("ix_focus_plans_owner_work", table_name="focus_plans")
    op.drop_index("ix_focus_plans_owner_created", table_name="focus_plans")
    op.drop_table("focus_plans")
    op.drop_index(
        "ix_focus_recommendations_owner_work_created",
        table_name="focus_plan_recommendations",
    )
    op.drop_table("focus_plan_recommendations")
