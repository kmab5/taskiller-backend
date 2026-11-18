from __future__ import annotations

import gzip
import hashlib
import json
import socket
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.db.models import Q

from taskiller.core.time import utc_now
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import (
    AccountDeletionRequest,
    AuthSession,
    DataExportRequest,
    EmailVerificationToken,
    ExecutionSession,
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
    IdempotencyRecord,
    OutboxJob,
    PasswordResetToken,
    RefreshToken,
    SecurityEvent,
    SessionEvent,
    SessionReview,
    TaskillerUser,
    UserPreferences,
    WorkItem,
    WorkType,
)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _model_dict(row: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    omitted = exclude or set()
    return {
        field.column: _json_value(getattr(row, field.attname))
        for field in row._meta.local_fields
        if field.column is not None and field.column not in omitted
    }


def recover_expired_leases() -> int:
    now = utc_now()
    recovered = 0
    with transaction.atomic():
        jobs = (
            OutboxJob.objects.select_for_update(skip_locked=True)
            .filter(status="running", lease_expires_at__lte=now)
            .order_by("id")
        )
        for job in jobs:
            _fail_locked_job(job, RuntimeError("lease expired"))
            recovered += 1
    return recovered


def ensure_retention_job(*, exclude_job_id: UUID | None = None, available_at=None) -> None:
    settings = taskiller_settings()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext('taskiller-retention-scheduler'))"
            )
        if (
            not OutboxJob.objects.filter(
                job_type="retention",
                status__in=["queued", "running"],
            )
            .exclude(id=exclude_job_id)
            .exists()
        ):
            now = utc_now()
            OutboxJob.objects.create(
                id=uuid4(),
                job_type="retention",
                payload_json={},
                status="queued",
                available_at=available_at or now,
                locked_at=None,
                locked_by=None,
                lease_expires_at=None,
                attempts=0,
                max_attempts=settings.outbox_max_attempts,
                last_error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )


def claim_job(worker: str, *, with_token: bool = False) -> UUID | tuple[UUID, str] | None:
    settings = taskiller_settings()
    now = utc_now()
    with transaction.atomic():
        job = (
            OutboxJob.objects.select_for_update(skip_locked=True)
            .filter(status="queued", available_at__lte=now)
            .order_by("available_at", "created_at", "id")
            .first()
        )
        if job is None:
            return None
        job.status = "running"
        job.locked_at = now
        job.locked_by = str(uuid4())
        job.lease_expires_at = now + timedelta(seconds=settings.outbox_lease_seconds)
        job.attempts += 1
        job.updated_at = now
        job.save()
        return (job.id, job.locked_by) if with_token else job.id


def _build_export_archive(export: DataExportRequest) -> None:
    settings = taskiller_settings()
    user = TaskillerUser.objects.filter(id=export.user_id).first()
    if user is None:
        raise RuntimeError("export user no longer exists")
    preferences = UserPreferences.objects.filter(user_id=export.user_id).first()

    work_types = list(
        WorkType.objects.filter(Q(owner_id=export.user_id) | Q(owner_id__isnull=True))
    )
    work_items = list(WorkItem.objects.filter(owner_id=export.user_id))
    recommendations = list(FocusPlanRecommendation.objects.filter(owner_id=export.user_id))
    plans = list(FocusPlan.objects.filter(owner_id=export.user_id))
    plan_ids = [row.id for row in plans]
    segments = list(FocusPlanSegment.objects.filter(focus_plan_id__in=plan_ids)) if plan_ids else []
    sessions = list(ExecutionSession.objects.filter(owner_id=export.user_id))
    events = list(SessionEvent.objects.filter(owner_id=export.user_id))
    reviews = list(SessionReview.objects.filter(owner_id=export.user_id))

    payload = {
        "format": "taskiller-data-export-v1",
        "generatedAt": utc_now().isoformat(),
        "user": _model_dict(user, exclude={"password_hash"}),
        "preferences": (_model_dict(preferences) if preferences is not None else None),
        "workTypes": [_model_dict(item) for item in work_types],
        "workItems": [_model_dict(item) for item in work_items],
        "focusPlanRecommendations": [_model_dict(item) for item in recommendations],
        "focusPlans": [_model_dict(item) for item in plans],
        "focusPlanSegments": [_model_dict(item) for item in segments],
        "executionSessions": [_model_dict(item) for item in sessions],
        "sessionEvents": [_model_dict(item) for item in events],
        "sessionReviews": [_model_dict(item) for item in reviews],
        "excludedSecrets": [
            "passwordHash",
            "refreshTokens",
            "emailVerificationTokens",
            "passwordResetTokens",
            "rateLimitBuckets",
            "internalOutboxJobs",
        ],
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    archive = gzip.compress(raw, compresslevel=6)
    now = utc_now()
    export.archive_bytes = archive
    export.archive_sha256 = hashlib.sha256(archive).hexdigest()
    export.archive_size_bytes = len(archive)
    export.status = "ready"
    export.completed_at = now
    export.expires_at = now + timedelta(hours=settings.export_ttl_hours)
    export.failure_code = None
    export.save()


def _hard_delete_account(deletion: AccountDeletionRequest) -> None:
    deletion.status = "processing"
    deletion.started_at = deletion.started_at or utc_now()
    deletion.save(update_fields=["status", "started_at"])

    user_id = deletion.user_id
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL taskiller.account_deletion = 'on'")
    # Relations deliberately use DO_NOTHING. Delete leaves explicitly, including
    # self-referencing refresh rotations before their sessions.
    SessionEvent.objects.filter(owner_id=user_id).delete()
    SessionReview.objects.filter(owner_id=user_id).delete()
    ExecutionSession.objects.filter(owner_id=user_id).delete()
    FocusPlanSegment.objects.filter(focus_plan__owner_id=user_id).delete()
    FocusPlan.objects.filter(owner_id=user_id).delete()
    FocusPlanRecommendation.objects.filter(owner_id=user_id).delete()
    for kind in ("chore", "sprint", "project"):
        WorkItem.objects.filter(owner_id=user_id, kind=kind).delete()
    WorkType.objects.filter(owner_id=user_id).delete()
    # Refresh locks session before token. Materialize these locks in stable order
    # before token UPDATE/DELETE so deletion cannot invert that ordering.
    list(AuthSession.objects.select_for_update().filter(user_id=user_id).order_by("id"))
    tokens = RefreshToken.objects.filter(session__user_id=user_id)
    RefreshToken.objects.filter(replaced_by_id__in=tokens.values("id")).update(replaced_by=None)
    tokens.delete()
    AuthSession.objects.filter(user_id=user_id).delete()
    EmailVerificationToken.objects.filter(user_id=user_id).delete()
    PasswordResetToken.objects.filter(user_id=user_id).delete()
    UserPreferences.objects.filter(user_id=user_id).delete()
    DataExportRequest.objects.filter(user_id=user_id).delete()
    IdempotencyRecord.objects.filter(owner_id=user_id).delete()
    # Do not lock auth_email outbox rows here: delivery holds its own job lock
    # before reading the owner. The delivery hook discards missing/inactive users.
    TaskillerUser.objects.filter(id=user_id).delete()

    deletion.status = "completed"
    deletion.completed_at = utc_now()
    deletion.failure_code = None
    deletion.save(update_fields=["status", "completed_at", "failure_code"])


def _run_retention() -> None:
    settings = taskiller_settings()
    now = utc_now()

    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM idempotency_records WHERE expires_at <= %s",
            [now],
        )
        cursor.execute(
            "DELETE FROM rate_limit_buckets WHERE updated_at <= %s",
            [now - timedelta(seconds=settings.rate_limit_bucket_retention_seconds)],
        )

    expired = RefreshToken.objects.filter(expires_at__lte=now)
    RefreshToken.objects.filter(replaced_by_id__in=expired.values("id")).update(replaced_by=None)
    expired.delete()
    EmailVerificationToken.objects.filter(expires_at__lte=now).delete()
    PasswordResetToken.objects.filter(expires_at__lte=now).delete()

    DataExportRequest.objects.filter(
        expires_at__isnull=False,
        expires_at__lte=now,
    ).update(archive_bytes=None, archive_size_bytes=None)

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL taskiller.retention = 'on'")

    SecurityEvent.objects.filter(
        created_at__lte=now - timedelta(days=settings.security_event_retention_days)
    ).delete()
    AccountDeletionRequest.objects.filter(
        status="completed",
        completed_at__lte=now - timedelta(days=settings.deletion_tombstone_retention_days),
    ).delete()
    OutboxJob.objects.filter(
        status__in=["succeeded", "dead"],
        completed_at__lte=now - timedelta(days=settings.outbox_history_retention_days),
    ).delete()


def _owns_claim(job: OutboxJob, claim_token: str | None) -> bool:
    if claim_token is None:
        # Legacy direct calls may process queued jobs, but cannot acknowledge a claim.
        return job.status == "queued" and job.locked_by is None
    return (
        job.status == "running"
        and job.locked_by == claim_token
        and job.lease_expires_at is not None
        and job.lease_expires_at > utc_now()
    )


def process_job(job_id: UUID, *, claim_token: str | None = None) -> bool:
    """Commit effects and acknowledgement together; retry serialization errors via the queue.

    A fresh REPEATABLE READ transaction is required so every export query uses
    one snapshot, including concurrent writes through uncoordinated API paths.
    """
    if connection.in_atomic_block:
        raise RuntimeError("process_job requires a fresh transaction")
    job_type = OutboxJob.objects.values_list("job_type", flat=True).get(id=job_id)
    with transaction.atomic():
        if job_type == "data_export":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        job = OutboxJob.objects.select_for_update().get(id=job_id)
        if job.job_type != job_type:
            raise RuntimeError("job type changed during processing")
        if not _owns_claim(job, claim_token):
            return False
        _process_locked_job(job)
        _finish_locked_job(job)
        return True


def _process_locked_job(job: OutboxJob) -> None:
    if job.job_type == "data_export":
        export_id = UUID(str(job.payload_json["exportRequestId"]))
        export = DataExportRequest.objects.select_for_update().filter(id=export_id).first()
        if export is not None and export.status != "ready":
            export.status = "processing"
            export.started_at = export.started_at or utc_now()
            export.save(update_fields=["status", "started_at"])
            _build_export_archive(export)
        return
    if job.job_type == "account_delete":
        request_id = UUID(str(job.payload_json["requestId"]))
        # Match application ordering: owner before deletion request/dependent rows.
        user_id = job.payload_json.get("userId")
        if user_id is not None:
            TaskillerUser.objects.select_for_update().filter(id=user_id).first()
        deletion = AccountDeletionRequest.objects.select_for_update().filter(id=request_id).first()
        if deletion is not None and deletion.status != "completed":
            _hard_delete_account(deletion)
        return
    if job.job_type == "auth_email":
        from taskiller.django_operations.email_delivery import deliver_auth_email

        deliver_auth_email(job.payload_json)
        return
    if job.job_type == "retention":
        _run_retention()
        ensure_retention_job(exclude_job_id=job.id, available_at=utc_now() + timedelta(hours=24))
        return
    raise RuntimeError(f"unsupported outbox job type: {job.job_type}")


def _finish_locked_job(job: OutboxJob) -> None:
    now = utc_now()
    job.status = "succeeded"
    job.completed_at = now
    job.updated_at = now
    job.locked_at = None
    job.locked_by = None
    job.lease_expires_at = None
    job.last_error = None
    job.save(
        update_fields=[
            "status",
            "completed_at",
            "updated_at",
            "locked_at",
            "locked_by",
            "lease_expires_at",
            "last_error",
        ]
    )


def finish_job(job_id: UUID, *, claim_token: str | None = None) -> bool:
    """Compatibility acknowledgement: queued direct calls only without a fence."""
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(id=job_id)
        if not _owns_claim(job, claim_token):
            return False
        _finish_locked_job(job)
        return True


def _fail_locked_job(job: OutboxJob, error: Exception) -> None:
    now = utc_now()
    terminal = job.attempts >= job.max_attempts
    job.status = "dead" if terminal else "queued"
    job.available_at = now + timedelta(seconds=min(300, 2 ** min(6, max(0, job.attempts - 1)) * 5))
    job.completed_at = now if terminal else None
    job.updated_at = now
    job.locked_at = None
    job.locked_by = None
    job.lease_expires_at = None
    # Provider exceptions may contain credentials/links: never persist them.
    job.last_error = type(error).__name__
    job.save()
    if terminal and job.job_type == "data_export":
        DataExportRequest.objects.filter(id=job.payload_json["exportRequestId"]).update(
            status="failed", failure_code="export_generation_failed"
        )
    if terminal and job.job_type == "account_delete":
        AccountDeletionRequest.objects.filter(id=job.payload_json["requestId"]).update(
            status="failed", failure_code="account_deletion_failed"
        )


def fail_job(job_id: UUID, error: Exception, *, claim_token: str | None = None) -> bool:
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(id=job_id)
        if not _owns_claim(job, claim_token):
            return False
        _fail_locked_job(job, error)
        return True


def worker_id() -> str:
    return f"{socket.gethostname()}:django"
