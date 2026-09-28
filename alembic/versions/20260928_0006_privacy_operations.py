"""Privacy lifecycle and PostgreSQL operations infrastructure."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0006"
down_revision: str | None = "20260928_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_export_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("archive_bytes", sa.LargeBinary()),
        sa.Column("archive_sha256", sa.String(64)),
        sa.Column("archive_size_bytes", sa.Integer()),
        sa.Column("failure_code", sa.String(80)),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed')",
            name="ck_data_export_status",
        ),
    )
    op.create_index(
        "ix_data_export_user_created",
        "data_export_requests",
        ["user_id", "created_at"],
    )
    op.create_index("ix_data_export_expiry", "data_export_requests", ["expires_at"])

    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(80)),
        sa.UniqueConstraint("user_id", name="uq_account_deletion_user"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'processing', 'completed', 'failed')",
            name="ck_account_deletion_status",
        ),
    )
    op.create_index(
        "ix_account_deletion_execute",
        "account_deletion_requests",
        ["status", "execute_after"],
    )

    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("job_type", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead')",
            name="ck_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_outbox_max_attempts_positive"),
    )
    op.create_index("ix_outbox_claim", "outbox_jobs", ["status", "available_at", "created_at"])
    op.create_index("ix_outbox_lease", "outbox_jobs", ["status", "lease_expires_at"])

    op.create_table(
        "rate_limit_buckets",
        sa.Column("scope", sa.String(100), primary_key=True),
        sa.Column("subject_hash", sa.String(64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rate_limit_updated", "rate_limit_buckets", ["updated_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID()),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("subject_hash", sa.String(64)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_events_user_time", "security_events", ["user_id", "created_at"])
    op.create_index("ix_security_events_created", "security_events", ["created_at"])

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION reject_security_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('taskiller.retention', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'security events are append-only';
        END;
        $$;
        CREATE TRIGGER security_events_append_only
        BEFORE UPDATE OR DELETE ON security_events
        FOR EACH ROW EXECUTE FUNCTION reject_security_event_mutation();
    """))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS security_events_append_only ON security_events")
    op.execute("DROP FUNCTION IF EXISTS reject_security_event_mutation()")
    op.drop_table("security_events")
    op.drop_table("rate_limit_buckets")
    op.drop_table("outbox_jobs")
    op.drop_table("account_deletion_requests")
    op.drop_table("data_export_requests")
