"""Add execution sessions, append-only events, and session reviews."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0004"
down_revision: str | None = "20260928_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("focus_plan_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("current_segment_index", sa.Integer(), nullable=False),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_segment_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("recommendation_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state IN ('running', 'paused', 'completed', 'abandoned')",
            name="ck_execution_sessions_state",
        ),
        sa.CheckConstraint(
            "current_segment_index >= 0", name="ck_execution_sessions_segment_index"
        ),
        sa.CheckConstraint("version >= 1", name="ck_execution_sessions_version_positive"),
        sa.CheckConstraint(
            "(state IN ('completed', 'abandoned') AND ended_at IS NOT NULL) OR "
            "(state IN ('running', 'paused') AND ended_at IS NULL)",
            name="ck_execution_sessions_end_state",
        ),
        sa.CheckConstraint(
            "(state = 'paused' AND paused_at IS NOT NULL) OR "
            "(state <> 'paused' AND paused_at IS NULL)",
            name="ck_execution_sessions_pause_state",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["focus_plan_id"], ["focus_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["focus_plan_recommendations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_execution_sessions_one_open_per_user",
        "execution_sessions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('running', 'paused')"),
    )
    op.create_index(
        "ix_execution_sessions_owner_started",
        "execution_sessions",
        ["owner_id", sa.text("session_started_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_execution_sessions_work_item_started",
        "execution_sessions",
        ["work_item_id", sa.text("session_started_at DESC")],
        unique=False,
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("segment_index", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_session_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('session_started', 'paused', 'resumed', 'segment_started', "
            "'segment_completed', 'segment_skipped', 'break_started', 'break_ended', "
            "'work_item_completed', 'session_completed', 'session_abandoned')",
            name="ck_session_events_type",
        ),
        sa.CheckConstraint(
            "segment_index IS NULL OR segment_index >= 0", name="ck_session_events_segment_index"
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 200",
            name="ck_session_events_idempotency_length",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["execution_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_session_events_idempotency"),
    )
    op.create_index(
        "ix_session_events_session_time",
        "session_events",
        ["session_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_session_events_owner_time",
        "session_events",
        ["owner_id", sa.text("occurred_at DESC")],
        unique=False,
    )

    op.create_table(
        "session_reviews",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("focus_score", sa.SmallInteger(), nullable=True),
        sa.Column("fatigue_score", sa.SmallInteger(), nullable=True),
        sa.Column("difficulty_score", sa.SmallInteger(), nullable=True),
        sa.Column("satisfaction_score", sa.SmallInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "focus_score IS NULL OR focus_score BETWEEN 1 AND 5",
            name="ck_session_reviews_focus",
        ),
        sa.CheckConstraint(
            "fatigue_score IS NULL OR fatigue_score BETWEEN 1 AND 5",
            name="ck_session_reviews_fatigue",
        ),
        sa.CheckConstraint(
            "difficulty_score IS NULL OR difficulty_score BETWEEN 1 AND 5",
            name="ck_session_reviews_difficulty",
        ),
        sa.CheckConstraint(
            "satisfaction_score IS NULL OR satisfaction_score BETWEEN 1 AND 5",
            name="ck_session_reviews_satisfaction",
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 4000", name="ck_session_reviews_note_length"
        ),
        sa.CheckConstraint("version >= 1", name="ck_session_reviews_version_positive"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["execution_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION validate_execution_session_references()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              wi_owner uuid;
              wi_kind text;
              fp_owner uuid;
              fp_work uuid;
              fp_template boolean;
              fp_deleted timestamptz;
              rec_owner uuid;
              rec_work uuid;
            BEGIN
              IF TG_OP = 'UPDATE' THEN
                IF (
                  NEW.owner_id <> OLD.owner_id OR
                  NEW.work_item_id <> OLD.work_item_id OR
                  NEW.focus_plan_id <> OLD.focus_plan_id OR
                  NEW.recommendation_id IS DISTINCT FROM OLD.recommendation_id OR
                  NEW.plan_snapshot_json IS DISTINCT FROM OLD.plan_snapshot_json OR
                  NEW.recommendation_snapshot_json IS DISTINCT FROM
                    OLD.recommendation_snapshot_json OR
                  NEW.session_started_at <> OLD.session_started_at OR
                  NEW.created_at <> OLD.created_at
                ) THEN
                  RAISE EXCEPTION 'execution session identity and snapshots are immutable';
                END IF;
                IF OLD.state IN ('completed', 'abandoned') AND NEW.state <> OLD.state THEN
                  RAISE EXCEPTION 'terminal execution session state is immutable';
                END IF;
                IF NEW.version <> OLD.version + 1 THEN
                  RAISE EXCEPTION 'execution session version must increment by one';
                END IF;
                RETURN NEW;
              END IF;

              SELECT owner_id, kind INTO wi_owner, wi_kind
              FROM work_items
              WHERE id = NEW.work_item_id AND deleted_at IS NULL;
              IF NOT FOUND OR wi_owner <> NEW.owner_id OR wi_kind NOT IN ('chore', 'sprint') THEN
                RAISE EXCEPTION 'invalid execution session work item reference';
              END IF;

              SELECT owner_id, work_item_id, is_template, deleted_at
              INTO fp_owner, fp_work, fp_template, fp_deleted
              FROM focus_plans
              WHERE id = NEW.focus_plan_id;
              IF NOT FOUND OR fp_owner <> NEW.owner_id OR fp_work <> NEW.work_item_id
                 OR fp_template OR fp_deleted IS NOT NULL THEN
                RAISE EXCEPTION 'invalid execution session focus plan reference';
              END IF;

              IF NEW.recommendation_id IS NOT NULL THEN
                SELECT owner_id, work_item_id INTO rec_owner, rec_work
                FROM focus_plan_recommendations
                WHERE id = NEW.recommendation_id;
                IF NOT FOUND OR rec_owner <> NEW.owner_id OR rec_work <> NEW.work_item_id THEN
                  RAISE EXCEPTION 'invalid execution session recommendation reference';
                END IF;
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
            CREATE TRIGGER execution_sessions_validate_references
            BEFORE INSERT OR UPDATE ON execution_sessions
            FOR EACH ROW EXECUTE FUNCTION validate_execution_session_references()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION validate_session_child_owner()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              session_owner uuid;
            BEGIN
              SELECT owner_id INTO session_owner
              FROM execution_sessions
              WHERE id = NEW.session_id;
              IF NOT FOUND OR session_owner <> NEW.owner_id THEN
                RAISE EXCEPTION 'session child owner must match execution session owner';
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
            CREATE TRIGGER session_events_validate_owner
            BEFORE INSERT OR UPDATE ON session_events
            FOR EACH ROW EXECUTE FUNCTION validate_session_child_owner()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION reject_session_event_updates()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'session events are append-only';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER session_events_append_only
            BEFORE UPDATE ON session_events
            FOR EACH ROW EXECUTE FUNCTION reject_session_event_updates()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER session_reviews_validate_owner
            BEFORE INSERT OR UPDATE ON session_reviews
            FOR EACH ROW EXECUTE FUNCTION validate_session_child_owner()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS session_events_append_only ON session_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_session_event_updates()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS session_reviews_validate_owner ON session_reviews"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS session_events_validate_owner ON session_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_session_child_owner()"))
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS execution_sessions_validate_references ON execution_sessions"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_execution_session_references()"))
    op.drop_table("session_reviews")
    op.drop_index("ix_session_events_owner_time", table_name="session_events")
    op.drop_index("ix_session_events_session_time", table_name="session_events")
    op.drop_table("session_events")
    op.drop_index("ix_execution_sessions_work_item_started", table_name="execution_sessions")
    op.drop_index("ix_execution_sessions_owner_started", table_name="execution_sessions")
    op.drop_index("uq_execution_sessions_one_open_per_user", table_name="execution_sessions")
    op.drop_table("execution_sessions")
