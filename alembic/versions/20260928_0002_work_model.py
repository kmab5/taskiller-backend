"""work model and idempotent mutations

Revision ID: 20260928_0002
Revises: 20260928_0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0002"
down_revision: str | None = "20260928_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYSTEM_WORK_TYPES = [
    (
        "e3d3e891-8760-4b08-8696-ad0fbc7292fd",
        "study_learning",
        "Study / Learning",
        "Learning new material.",
        "high",
        "medium",
        "medium",
        "low",
        "sedentary",
        "acquisition",
    ),
    (
        "3d4f906a-8d02-4915-9400-7e9d5108ce53",
        "reading",
        "Reading",
        "Focused reading or review of written material.",
        "medium",
        "medium",
        "medium",
        "low",
        "sedentary",
        "acquisition",
    ),
    (
        "ec4ea345-eba5-4af9-84bf-799b0a151fc3",
        "writing",
        "Writing",
        "Drafting or revising written material.",
        "high",
        "high",
        "high",
        "low",
        "sedentary",
        "none",
    ),
    (
        "f3b8f3f9-1ec6-4185-8901-d2e87dc3b059",
        "programming",
        "Programming",
        "Software implementation and debugging.",
        "high",
        "high",
        "high",
        "low",
        "sedentary",
        "none",
    ),
    (
        "ec12f3fa-9770-446a-acfd-78be78e47c2b",
        "problem_solving",
        "Problem Solving",
        "Analytical problems, exercises, or technical reasoning.",
        "high",
        "high",
        "high",
        "low",
        "sedentary",
        "practice",
    ),
    (
        "2c966900-f837-4c3f-a96e-407c40ec92d4",
        "creative_generation",
        "Creative Generation",
        "Open-ended creative production.",
        "high",
        "high",
        "high",
        "low",
        "sedentary",
        "none",
    ),
    (
        "6407c9c8-65df-4d7b-a25d-41de06a86700",
        "brainstorming_planning",
        "Brainstorming / Planning",
        "Idea generation, structuring, and planning.",
        "high",
        "medium",
        "medium",
        "low",
        "sedentary",
        "none",
    ),
    (
        "b075afca-77ad-4361-a203-c3e3f1f43d4c",
        "administration",
        "Administration",
        "Forms, organization, routine management work.",
        "medium",
        "low",
        "low",
        "high",
        "sedentary",
        "none",
    ),
    (
        "39c7a56a-d72a-4ad1-b95d-95e434c7a5f3",
        "communication",
        "Communication",
        "Email, messages, calls, and coordination.",
        "medium",
        "low",
        "low",
        "medium",
        "sedentary",
        "none",
    ),
    (
        "9f49e1f5-13d8-4132-a87f-0d29f69a6399",
        "repetitive_processing",
        "Repetitive Processing",
        "Repeated low-context processing work.",
        "medium",
        "low",
        "low",
        "high",
        "sedentary",
        "none",
    ),
    (
        "520f715c-672e-4795-a7d1-7ff84bd2dc2b",
        "physical_chore",
        "Physical Chore",
        "Physical or household/personal execution work.",
        "low",
        "low",
        "low",
        "medium",
        "active",
        "none",
    ),
]


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body_json", sa.JSON(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 200",
            name="ck_idempotency_key_length",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_id", "scope", "idempotency_key"),
    )
    op.create_index(
        "ix_idempotency_records_expiry",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "work_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("cognitive_demand", sa.String(length=20), nullable=False),
        sa.Column("interruption_sensitivity", sa.String(length=20), nullable=False),
        sa.Column("continuity_need", sa.String(length=20), nullable=False),
        sa.Column("repetitiveness", sa.String(length=20), nullable=False),
        sa.Column("physicality", sa.String(length=20), nullable=False),
        sa.Column("learning_mode", sa.String(length=20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(owner_id IS NULL AND is_system) OR (owner_id IS NOT NULL AND NOT is_system)",
            name="ck_work_types_owner_system",
        ),
        sa.CheckConstraint(
            "cognitive_demand IN ('low', 'medium', 'high')",
            name="ck_work_types_cognitive_demand",
        ),
        sa.CheckConstraint(
            "interruption_sensitivity IN ('low', 'medium', 'high')",
            name="ck_work_types_interruption_sensitivity",
        ),
        sa.CheckConstraint(
            "continuity_need IN ('low', 'medium', 'high')",
            name="ck_work_types_continuity_need",
        ),
        sa.CheckConstraint(
            "repetitiveness IN ('low', 'medium', 'high')",
            name="ck_work_types_repetitiveness",
        ),
        sa.CheckConstraint(
            "physicality IN ('sedentary', 'light', 'active')",
            name="ck_work_types_physicality",
        ),
        sa.CheckConstraint(
            "learning_mode IN ('none', 'acquisition', 'retrieval', 'practice')",
            name="ck_work_types_learning_mode",
        ),
        sa.CheckConstraint("version >= 1", name="ck_work_types_version_positive"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_work_types_system_slug",
        "work_types",
        [sa.text("lower(slug)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    op.create_index(
        "uq_work_types_owner_slug",
        "work_types",
        ["owner_id", sa.text("lower(slug)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )

    work_types_table = sa.table(
        "work_types",
        sa.column("id", sa.Uuid()),
        sa.column("owner_id", sa.Uuid()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("cognitive_demand", sa.String()),
        sa.column("interruption_sensitivity", sa.String()),
        sa.column("continuity_need", sa.String()),
        sa.column("repetitiveness", sa.String()),
        sa.column("physicality", sa.String()),
        sa.column("learning_mode", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer()),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        work_types_table,
        [
            {
                "id": UUID(item[0]),
                "owner_id": None,
                "slug": item[1],
                "display_name": item[2],
                "description": item[3],
                "cognitive_demand": item[4],
                "interruption_sensitivity": item[5],
                "continuity_need": item[6],
                "repetitiveness": item[7],
                "physicality": item[8],
                "learning_mode": item[9],
                "is_system": True,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            for item in _SYSTEM_WORK_TYPES
        ],
    )

    op.create_table(
        "work_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("work_type_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("estimated_effort_seconds", sa.Integer(), nullable=True),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_start_date", sa.Date(), nullable=True),
        sa.Column("target_end_date", sa.Date(), nullable=True),
        sa.Column("cognitive_demand_override", sa.String(length=20), nullable=True),
        sa.Column("interruption_sensitivity_override", sa.String(length=20), nullable=True),
        sa.Column("continuity_need_override", sa.String(length=20), nullable=True),
        sa.Column("repetitiveness_override", sa.String(length=20), nullable=True),
        sa.Column("physicality_override", sa.String(length=20), nullable=True),
        sa.Column("learning_mode_override", sa.String(length=20), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('project', 'sprint', 'chore')", name="ck_work_items_kind"),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'in_progress', 'completed', 'cancelled', 'archived')",
            name="ck_work_items_status",
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 300", name="ck_work_items_name"),
        sa.CheckConstraint(
            "priority IS NULL OR priority BETWEEN 0 AND 5",
            name="ck_work_items_priority",
        ),
        sa.CheckConstraint(
            "estimated_effort_seconds IS NULL OR "
            "estimated_effort_seconds BETWEEN 0 AND 31536000",
            name="ck_work_items_estimate",
        ),
        sa.CheckConstraint(
            "planned_start_at IS NULL OR deadline_at IS NULL OR planned_start_at <= deadline_at",
            name="ck_work_items_planned_range",
        ),
        sa.CheckConstraint(
            "target_start_date IS NULL OR target_end_date IS NULL OR "
            "target_start_date <= target_end_date",
            name="ck_work_items_target_range",
        ),
        sa.CheckConstraint(
            "kind = 'project' OR (target_start_date IS NULL AND target_end_date IS NULL)",
            name="ck_work_items_project_dates",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="ck_work_items_completed_timestamp",
        ),
        sa.CheckConstraint(
            "status <> 'cancelled' OR cancelled_at IS NOT NULL",
            name="ck_work_items_cancelled_timestamp",
        ),
        sa.CheckConstraint(
            "status <> 'archived' OR archived_at IS NOT NULL",
            name="ck_work_items_archived_timestamp",
        ),
        sa.CheckConstraint("version >= 1", name="ck_work_items_version_positive"),
        sa.CheckConstraint(
            "cognitive_demand_override IS NULL OR "
            "cognitive_demand_override IN ('low', 'medium', 'high')",
            name="ck_work_items_cognitive_override",
        ),
        sa.CheckConstraint(
            "interruption_sensitivity_override IS NULL OR "
            "interruption_sensitivity_override IN ('low', 'medium', 'high')",
            name="ck_work_items_interruption_override",
        ),
        sa.CheckConstraint(
            "continuity_need_override IS NULL OR "
            "continuity_need_override IN ('low', 'medium', 'high')",
            name="ck_work_items_continuity_override",
        ),
        sa.CheckConstraint(
            "repetitiveness_override IS NULL OR "
            "repetitiveness_override IN ('low', 'medium', 'high')",
            name="ck_work_items_repetitiveness_override",
        ),
        sa.CheckConstraint(
            "physicality_override IS NULL OR "
            "physicality_override IN ('sedentary', 'light', 'active')",
            name="ck_work_items_physicality_override",
        ),
        sa.CheckConstraint(
            "learning_mode_override IS NULL OR "
            "learning_mode_override IN ('none', 'acquisition', 'retrieval', 'practice')",
            name="ck_work_items_learning_override",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["work_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_type_id"], ["work_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_items_owner_status_kind",
        "work_items",
        ["owner_id", "status", "kind"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_work_items_owner_parent_position",
        "work_items",
        ["owner_id", "parent_id", "position", "id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_work_items_owner_created",
        "work_items",
        ["owner_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_work_items_owner_deadline",
        "work_items",
        ["owner_id", "deadline_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL AND deadline_at IS NOT NULL"),
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION validate_work_item_hierarchy()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              p_kind text;
              p_owner uuid;
            BEGIN
              IF TG_OP = 'UPDATE' AND NEW.kind <> OLD.kind THEN
                RAISE EXCEPTION 'work item kind is immutable';
              END IF;
              IF TG_OP = 'UPDATE' AND NEW.owner_id <> OLD.owner_id THEN
                RAISE EXCEPTION 'work item owner is immutable';
              END IF;
              IF TG_OP = 'UPDATE' AND NEW.status <> OLD.status THEN
                IF NOT (
                  (OLD.status = 'draft' AND NEW.status IN ('ready', 'cancelled')) OR
                  (OLD.status = 'ready' AND NEW.status IN (
                    'in_progress', 'completed', 'cancelled', 'archived'
                  )) OR
                  (OLD.status = 'in_progress' AND NEW.status IN ('completed', 'cancelled')) OR
                  (OLD.status = 'completed' AND NEW.status IN ('ready', 'archived')) OR
                  (OLD.status = 'cancelled' AND NEW.status IN ('ready', 'archived')) OR
                  (OLD.status = 'archived' AND NEW.status = 'ready')
                ) THEN
                  RAISE EXCEPTION 'invalid work item state transition';
                END IF;
              END IF;
              IF (
                TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
                AND EXISTS (
                  SELECT 1 FROM work_items
                  WHERE parent_id = NEW.id AND deleted_at IS NULL
                )
              ) THEN
                RAISE EXCEPTION 'work item with live children cannot be deleted';
              END IF;

              IF NEW.kind = 'project' THEN
                IF NEW.parent_id IS NOT NULL THEN
                  RAISE EXCEPTION 'project cannot have a parent';
                END IF;
                RETURN NEW;
              END IF;

              IF NEW.kind = 'sprint' AND NEW.parent_id IS NULL THEN
                RAISE EXCEPTION 'sprint must have a project parent';
              END IF;

              IF NEW.parent_id IS NULL THEN
                IF NEW.kind <> 'chore' THEN
                  RAISE EXCEPTION 'only chores may be parentless';
                END IF;
                RETURN NEW;
              END IF;

              SELECT kind, owner_id INTO p_kind, p_owner
              FROM work_items
              WHERE id = NEW.parent_id AND deleted_at IS NULL;

              IF NOT FOUND THEN
                RAISE EXCEPTION 'parent work item not found';
              END IF;
              IF p_owner <> NEW.owner_id THEN
                RAISE EXCEPTION 'parent and child owner must match';
              END IF;
              IF NEW.kind = 'sprint' AND p_kind <> 'project' THEN
                RAISE EXCEPTION 'sprint parent must be project';
              END IF;
              IF NEW.kind = 'chore' AND p_kind NOT IN ('project', 'sprint') THEN
                RAISE EXCEPTION 'chore parent must be project or sprint';
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER work_items_validate_hierarchy
            BEFORE INSERT OR UPDATE OF kind, parent_id, owner_id, status, deleted_at ON work_items
            FOR EACH ROW EXECUTE FUNCTION validate_work_item_hierarchy()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS work_items_validate_hierarchy ON work_items"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_work_item_hierarchy()"))
    op.drop_index("ix_work_items_owner_deadline", table_name="work_items")
    op.drop_index("ix_work_items_owner_created", table_name="work_items")
    op.drop_index("ix_work_items_owner_parent_position", table_name="work_items")
    op.drop_index("ix_work_items_owner_status_kind", table_name="work_items")
    op.drop_table("work_items")
    op.drop_index("uq_work_types_owner_slug", table_name="work_types")
    op.drop_index("uq_work_types_system_slug", table_name="work_types")
    op.drop_table("work_types")
    op.drop_index("ix_idempotency_records_expiry", table_name="idempotency_records")
    op.drop_table("idempotency_records")
