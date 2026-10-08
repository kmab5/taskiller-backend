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
    DataExportRequest,
    EmailVerificationToken,
    ExecutionSession,
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
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
    return OutboxJob.objects.filter(
        status="running",
        lease_expires_at__lte=now,
    ).update(
        status="queued",
        locked_at=None,
        locked_by=None,
        lease_expires_at=None,
        available_at=now,
        updated_at=now,
    )


def ensure_retention_job() -> None:
    settings = taskiller_settings()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext('taskiller-retention-scheduler'))"
            )
        if not OutboxJob.objects.filter(
            job_type="retention",
            status__in=["queued", "running"],
        ).exists():
            now = utc_now()
            OutboxJob.objects.create(
                id=uuid4(),
                job_type="retention",
                payload_json={},
                status="queued",
                available_at=now,
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


def claim_job(worker: str) -> UUID | None:
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
        job.locked_by = worker
        job.lease_expires_at = now + timedelta(seconds=settings.outbox_lease_seconds)
        job.attempts += 1
        job.updated_at = now
        job.save()
        return job.id


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

    ExecutionSession.objects.filter(owner_id=deletion.user_id).delete()
    for kind in ("chore", "sprint", "project"):
        WorkItem.objects.filter(
            owner_id=deletion.user_id,
            kind=kind,
        ).delete()
    TaskillerUser.objects.filter(id=deletion.user_id).delete()

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

    RefreshToken.objects.filter(expires_at__lte=now).delete()
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


def process_job(job_id: UUID) -> None:
    settings = taskiller_settings()
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(id=job_id)

        if job.job_type == "data_export":
            export_id = UUID(str(job.payload_json["exportRequestId"]))
            export = DataExportRequest.objects.select_for_update().filter(id=export_id).first()
            if export is None:
                return
            export.status = "processing"
            export.started_at = export.started_at or utc_now()
            export.save(update_fields=["status", "started_at"])
            _build_export_archive(export)
            return

        if job.job_type == "account_delete":
            request_id = UUID(str(job.payload_json["requestId"]))
            deletion = (
                AccountDeletionRequest.objects.select_for_update().filter(id=request_id).first()
            )
            if deletion is None or deletion.status == "completed":
                return
            _hard_delete_account(deletion)
            return

        if job.job_type == "retention":
            _run_retention()
            now = utc_now()
            OutboxJob.objects.create(
                id=uuid4(),
                job_type="retention",
                payload_json={},
                status="queued",
                available_at=now + timedelta(hours=24),
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
            return

        raise RuntimeError(f"unsupported outbox job type: {job.job_type}")


def finish_job(job_id: UUID) -> None:
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(id=job_id)
        now = utc_now()
        job.status = "succeeded"
        job.completed_at = now
        job.updated_at = now
        job.locked_at = None
        job.locked_by = None
        job.lease_expires_at = None
        job.last_error = None
        job.save()


def fail_job(job_id: UUID, error: Exception) -> None:
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(id=job_id)
        now = utc_now()
        terminal = job.attempts >= job.max_attempts
        job.status = "dead" if terminal else "queued"
        job.available_at = now + timedelta(
            seconds=min(
                300,
                2 ** max(0, job.attempts - 1) * 5,
            )
        )
        job.completed_at = now if terminal else None
        job.updated_at = now
        job.locked_at = None
        job.locked_by = None
        job.lease_expires_at = None
        job.last_error = f"{type(error).__name__}: {error}"[:2000]
        job.save()

        if job.job_type == "data_export" and terminal:
            export_id = UUID(str(job.payload_json["exportRequestId"]))
            DataExportRequest.objects.filter(id=export_id).update(
                status="failed",
                failure_code="export_generation_failed",
            )
        if job.job_type == "account_delete" and terminal:
            request_id = UUID(str(job.payload_json["requestId"]))
            AccountDeletionRequest.objects.filter(id=request_id).update(
                status="failed",
                failure_code="account_deletion_failed",
            )


def worker_id() -> str:
    return f"{socket.gethostname()}:django"
