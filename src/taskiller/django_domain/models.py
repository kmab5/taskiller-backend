from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.db.models.functions import Lower

DO_NOTHING = models.DO_NOTHING


class PsycopgCompatibleJSONField(models.JSONField):
    """Accept psycopg JSONB values decoded by either driver or Django.

    Django expects JSONB from PostgreSQL to arrive as JSON text. Some psycopg
    connection configurations return the decoded Python value instead. Without
    this guard Django JSONField.from_db_value invokes json.loads(dict) and
    crashes session history, analytics and other JSON-backed endpoints.
    """

    def from_db_value(self, value, expression, connection):
        if value is None or not isinstance(value, (str, bytes, bytearray)):
            return value
        return super().from_db_value(value, expression, connection)

    def deconstruct(self):
        name, _path, args, kwargs = super().deconstruct()
        # This is a Python-side decoder compatibility fix, not a schema change.
        # Keep migration state identical to the existing JSONField migration.
        return name, "django.db.models.JSONField", args, kwargs


class ExistingTaskillerModel(models.Model):
    class Meta:
        abstract = True
        managed = True


class TaskillerUser(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    email = models.CharField(max_length=320)
    password_hash = models.TextField()
    display_name = models.CharField(max_length=200, null=True)
    email_verified_at = models.DateTimeField(null=True)
    password_changed_at = models.DateTimeField()
    is_active = models.BooleanField()
    version = models.IntegerField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "users"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(Lower("email"), name="tk_users_email_ci_unique"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="tk_users_version"),
        ]
        verbose_name = "Taskiller user"
        verbose_name_plural = "Taskiller users"

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def __str__(self) -> str:
        return self.email


class UserPreferences(ExistingTaskillerModel):
    user = models.OneToOneField(
        TaskillerUser,
        primary_key=True,
        db_column="user_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_preferences",
    )
    timezone = models.CharField(max_length=100)
    locale = models.CharField(max_length=40)
    week_starts_on = models.SmallIntegerField()
    preferred_strategy = models.CharField(max_length=20)
    preferred_work_block_min_seconds = models.IntegerField(null=True)
    preferred_work_block_max_seconds = models.IntegerField(null=True)
    show_review_prompt = models.BooleanField()
    version = models.IntegerField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "user_preferences"
        verbose_name_plural = "User preferences"


class AuthSession(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(
        TaskillerUser,
        db_column="user_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_auth_sessions",
    )
    device_name = models.CharField(max_length=200, null=True)
    created_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    revocation_reason = models.CharField(max_length=80, null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "auth_sessions"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_auth_sessions_expiry")
        ]


class RefreshToken(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(
        AuthSession,
        db_column="session_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_refresh_tokens",
    )
    token_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    replaced_by = models.ForeignKey(
        "self",
        db_column="replaced_by_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="+",
    )

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "refresh_tokens"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["token_hash"], name="tk_refresh_hash")
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_refresh_expiry")
        ]


class EmailVerificationToken(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(
        TaskillerUser,
        db_column="user_id",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    token_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "email_verification_tokens"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["token_hash"], name="tk_verify_hash")
        ]


class PasswordResetToken(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(
        TaskillerUser,
        db_column="user_id",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    token_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "password_reset_tokens"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["token_hash"], name="tk_reset_hash")
        ]


class IdempotencyRecord(ExistingTaskillerModel):
    pk = models.CompositePrimaryKey("owner_id", "scope", "idempotency_key")
    owner_id = models.UUIDField()
    scope = models.CharField(max_length=160)
    idempotency_key = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)
    response_status = models.IntegerField(null=True)
    response_body_json = PsycopgCompatibleJSONField(null=True)
    resource_id = models.UUIDField(null=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "idempotency_records"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_idempotency_expiry")
        ]


class WorkType(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_work_types",
    )
    slug = models.CharField(max_length=64)
    display_name = models.CharField(max_length=120)
    description = models.CharField(max_length=1000, null=True)
    cognitive_demand = models.CharField(max_length=20)
    interruption_sensitivity = models.CharField(max_length=20)
    continuity_need = models.CharField(max_length=20)
    repetitiveness = models.CharField(max_length=20)
    physicality = models.CharField(max_length=20)
    learning_mode = models.CharField(max_length=20)
    is_system = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    version = models.IntegerField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "work_types"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                Lower("slug"),
                "owner",
                condition=models.Q(owner__isnull=False),
                name="tk_work_type_owner_slug",
            ),
            models.UniqueConstraint(
                Lower("slug"),
                condition=models.Q(owner__isnull=True),
                name="tk_work_type_system_slug",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_system=True, owner__isnull=True)
                    | models.Q(is_system=False, owner__isnull=False)
                ),
                name="tk_work_type_ownership",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name


class WorkItem(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_work_items",
    )
    kind = models.CharField(max_length=20)
    parent = models.ForeignKey(
        "self",
        db_column="parent_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_children",
    )
    work_type = models.ForeignKey(
        WorkType,
        db_column="work_type_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_work_items",
    )
    name = models.CharField(max_length=300)
    description = models.TextField(null=True)
    status = models.CharField(max_length=20)
    position = models.BigIntegerField()
    priority = models.SmallIntegerField(null=True)
    estimated_effort_seconds = models.IntegerField(null=True)
    planned_start_at = models.DateTimeField(null=True)
    deadline_at = models.DateTimeField(null=True)
    target_start_date = models.DateField(null=True)
    target_end_date = models.DateField(null=True)
    cognitive_demand_override = models.CharField(max_length=20, null=True)
    interruption_sensitivity_override = models.CharField(max_length=20, null=True)
    continuity_need_override = models.CharField(max_length=20, null=True)
    repetitiveness_override = models.CharField(max_length=20, null=True)
    physicality_override = models.CharField(max_length=20, null=True)
    learning_mode_override = models.CharField(max_length=20, null=True)
    completed_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)
    archived_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    version = models.IntegerField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "work_items"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["project", "sprint", "chore"]),
                name="tk_work_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "ready",
                        "in_progress",
                        "completed",
                        "cancelled",
                        "archived",
                    ]
                ),
                name="tk_work_status",
            ),
            models.CheckConstraint(
                condition=(~models.Q(kind="project") | models.Q(parent__isnull=True)),
                name="tk_project_root",
            ),
            models.CheckConstraint(
                condition=(~models.Q(kind="sprint") | models.Q(parent__isnull=False)),
                name="tk_sprint_parent",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")),
                name="tk_work_not_self_parent",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="tk_work_version"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["owner", "parent", "position"],
                name="tk_work_siblings",
                condition=models.Q(deleted_at__isnull=True),
            )
        ]

    def __str__(self) -> str:
        return self.name


class FocusPlanRecommendation(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    work_item = models.ForeignKey(
        WorkItem,
        db_column="work_item_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_recommendations",
    )
    engine_version = models.CharField(max_length=40)
    provenance = models.CharField(max_length=40)
    strategy = models.CharField(max_length=40)
    input_snapshot_json = PsycopgCompatibleJSONField()
    plan_snapshot_json = PsycopgCompatibleJSONField()
    reasons_json = PsycopgCompatibleJSONField()
    created_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "focus_plan_recommendations"


class FocusPlan(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_focus_plans",
    )
    work_item = models.ForeignKey(
        WorkItem,
        db_column="work_item_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_focus_plans",
    )
    recommendation = models.ForeignKey(
        FocusPlanRecommendation,
        db_column="recommendation_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_focus_plans",
    )
    source = models.CharField(max_length=30)
    name = models.CharField(max_length=200)
    is_template = models.BooleanField()
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    version = models.IntegerField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "focus_plans"

    def __str__(self) -> str:
        return self.name


class FocusPlanSegment(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    focus_plan = models.ForeignKey(
        FocusPlan,
        db_column="focus_plan_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_segments",
    )
    segment_index = models.SmallIntegerField()
    kind = models.CharField(max_length=30)
    duration_mode = models.CharField(max_length=20)
    target_seconds = models.IntegerField(null=True)
    min_seconds = models.IntegerField(null=True)
    max_seconds = models.IntegerField(null=True)
    linked_work_item = models.ForeignKey(
        WorkItem,
        db_column="linked_work_item_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="+",
    )
    optional = models.BooleanField()
    label = models.CharField(max_length=300, null=True)
    instructions = models.TextField(null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "focus_plan_segments"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["focus_plan", "segment_index"],
                name="tk_plan_segment_index",
            ),
            models.CheckConstraint(
                condition=models.Q(segment_index__gte=0),
                name="tk_segment_nonnegative",
            ),
        ]


class ExecutionSession(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_execution_sessions",
    )
    work_item = models.ForeignKey(
        WorkItem,
        db_column="work_item_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_execution_sessions",
    )
    focus_plan = models.ForeignKey(
        FocusPlan,
        db_column="focus_plan_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_execution_sessions",
    )
    recommendation = models.ForeignKey(
        FocusPlanRecommendation,
        db_column="recommendation_id",
        on_delete=DO_NOTHING,
        null=True,
        related_name="taskiller_execution_sessions",
    )
    state = models.CharField(max_length=20)
    current_segment_index = models.IntegerField()
    session_started_at = models.DateTimeField()
    current_segment_started_at = models.DateTimeField(null=True)
    paused_at = models.DateTimeField(null=True)
    ended_at = models.DateTimeField(null=True)
    plan_snapshot_json = PsycopgCompatibleJSONField()
    recommendation_snapshot_json = PsycopgCompatibleJSONField(null=True)
    work_context_snapshot_json = PsycopgCompatibleJSONField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    version = models.IntegerField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "execution_sessions"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["owner"],
                condition=models.Q(state__in=["running", "paused"]),
                name="tk_one_open_session",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["running", "paused", "completed", "abandoned"]),
                name="tk_session_state",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="tk_session_version"),
        ]


class SessionEvent(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(
        ExecutionSession,
        db_column="session_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_events",
    )
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    type = models.CharField(max_length=40)
    occurred_at = models.DateTimeField()
    client_occurred_at = models.DateTimeField(null=True)
    segment_index = models.IntegerField(null=True)
    idempotency_key = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)
    payload_json = PsycopgCompatibleJSONField()
    result_session_snapshot_json = PsycopgCompatibleJSONField()
    created_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "session_events"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["session", "idempotency_key"],
                name="tk_session_event_key",
            )
        ]


class SessionReview(ExistingTaskillerModel):
    session = models.OneToOneField(
        ExecutionSession,
        primary_key=True,
        db_column="session_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_review",
    )
    owner = models.ForeignKey(
        TaskillerUser,
        db_column="owner_id",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    focus_score = models.SmallIntegerField(null=True)
    fatigue_score = models.SmallIntegerField(null=True)
    difficulty_score = models.SmallIntegerField(null=True)
    satisfaction_score = models.SmallIntegerField(null=True)
    note = models.TextField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    version = models.IntegerField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "session_reviews"


class DataExportRequest(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(
        TaskillerUser,
        db_column="user_id",
        on_delete=DO_NOTHING,
        related_name="taskiller_exports",
    )
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)
    archive_bytes = models.BinaryField(null=True)
    archive_sha256 = models.CharField(max_length=64, null=True)
    archive_size_bytes = models.IntegerField(null=True)
    failure_code = models.CharField(max_length=80, null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "data_export_requests"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_export_expiry")
        ]


class AccountDeletionRequest(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user_id = models.UUIDField()
    status = models.CharField(max_length=20)
    requested_at = models.DateTimeField()
    execute_after = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    failure_code = models.CharField(max_length=80, null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "account_deletion_requests"


class OutboxJob(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    job_type = models.CharField(max_length=80)
    payload_json = PsycopgCompatibleJSONField()
    status = models.CharField(max_length=20)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True)
    locked_by = models.CharField(max_length=160, null=True)
    lease_expires_at = models.DateTimeField(null=True)
    attempts = models.IntegerField()
    max_attempts = models.IntegerField()
    last_error = models.TextField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True)

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "outbox_jobs"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["available_at", "created_at"],
                condition=models.Q(status="queued"),
                name="tk_outbox_due",
            ),
            models.Index(
                fields=["lease_expires_at"],
                condition=models.Q(status="running"),
                name="tk_outbox_leases",
            ),
        ]


class RateLimitBucket(ExistingTaskillerModel):
    pk = models.CompositePrimaryKey("scope", "subject_hash")
    scope = models.CharField(max_length=100)
    subject_hash = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    count = models.IntegerField()
    updated_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "rate_limit_buckets"


class SecurityEvent(ExistingTaskillerModel):
    id = models.UUIDField(primary_key=True)
    user_id = models.UUIDField(null=True)
    event_type = models.CharField(max_length=100)
    subject_hash = models.CharField(max_length=64, null=True)
    user_agent = models.CharField(max_length=300, null=True)
    metadata_json = PsycopgCompatibleJSONField()
    created_at = models.DateTimeField()

    class Meta(ExistingTaskillerModel.Meta):
        db_table = "security_events"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["created_at"], name="tk_security_retention")
        ]
