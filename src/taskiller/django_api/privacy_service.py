from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.db import transaction

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.idempotency import (
    claim_idempotency,
    complete_idempotency,
)
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import (
    AccountDeletionRequest,
    AuthSession,
    DataExportRequest,
    OutboxJob,
    TaskillerUser,
)
from taskiller.operations.tokens import (
    create_export_download_token,
    verify_export_download_token,
)
from taskiller.users.etag import make_etag


def _enqueue_job(
    *,
    job_type: str,
    payload: dict[str, object],
    available_at: datetime | None = None,
) -> OutboxJob:
    settings = taskiller_settings()
    now = utc_now()
    return OutboxJob.objects.create(
        id=uuid4(),
        job_type=job_type,
        payload_json=payload,
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


def request_data_export(
    *,
    user_id: UUID,
    idempotency_key: str,
) -> DataExportRequest:
    settings = taskiller_settings()
    with transaction.atomic():
        replay = claim_idempotency(
            owner_id=user_id,
            scope="data-export:create",
            key=idempotency_key,
            request_payload={},
            ttl_hours=settings.idempotency_ttl_hours,
        )
        if replay is not None and replay.resource_id is not None:
            existing = DataExportRequest.objects.filter(id=replay.resource_id).first()
            if existing is None:
                raise TaskillerAPIError(
                    409,
                    "idempotency_replay_missing",
                    "Export replay unavailable",
                )
            return existing

        now = utc_now()
        export = DataExportRequest.objects.create(
            id=uuid4(),
            user_id=user_id,
            status="queued",
            created_at=now,
            started_at=None,
            completed_at=None,
            expires_at=None,
            archive_bytes=None,
            archive_sha256=None,
            archive_size_bytes=None,
            failure_code=None,
        )
        _enqueue_job(
            job_type="data_export",
            payload={
                "exportRequestId": str(export.id),
                "userId": str(user_id),
            },
        )
        complete_idempotency(
            owner_id=user_id,
            scope="data-export:create",
            key=idempotency_key,
            response_status=202,
            response_body={"requestId": str(export.id), "status": "queued"},
            resource_id=export.id,
        )
        return export


def schedule_account_deletion(
    user: TaskillerUser,
    if_match: str | None,
) -> AccountDeletionRequest:
    settings = taskiller_settings()
    now = utc_now()
    with transaction.atomic():
        locked_user = TaskillerUser.objects.select_for_update().get(id=user.id)
        expected = make_etag("user", locked_user.id, locked_user.version)
        if if_match is None or if_match.strip() != expected:
            raise TaskillerAPIError(
                412,
                "precondition_failed",
                "Resource version mismatch",
                "Refresh the resource and retry using its latest ETag.",
                headers={"ETag": expected},
            )

        existing = (
            AccountDeletionRequest.objects.select_for_update()
            .filter(user_id=locked_user.id)
            .first()
        )
        if existing is not None:
            return existing

        execute_after = now + timedelta(days=settings.account_deletion_grace_days)
        deletion = AccountDeletionRequest.objects.create(
            id=uuid4(),
            user_id=locked_user.id,
            status="scheduled",
            requested_at=now,
            execute_after=execute_after,
            started_at=None,
            completed_at=None,
            failure_code=None,
        )

        sessions = list(
            AuthSession.objects.select_for_update().filter(
                user_id=locked_user.id, revoked_at__isnull=True
            )
        )
        for session in sessions:
            session.revoked_at = now
            session.revocation_reason = "account_deletion_scheduled"
            session.save(update_fields=["revoked_at", "revocation_reason"])

        locked_user.is_active = False
        locked_user.version += 1
        locked_user.updated_at = now
        locked_user.save(update_fields=["is_active", "version", "updated_at"])

        _enqueue_job(
            job_type="account_delete",
            payload={
                "requestId": str(deletion.id),
                "userId": str(locked_user.id),
            },
            available_at=execute_after,
        )
        return deletion


def export_response(row: DataExportRequest) -> dict[str, object]:
    settings = taskiller_settings()
    now = utc_now()
    download_url: str | None = None
    if row.status == "ready" and row.expires_at is not None and row.expires_at > now:
        token_expiry = min(
            row.expires_at,
            now + timedelta(seconds=settings.export_download_ttl_seconds),
        )
        token = create_export_download_token(
            row.id,
            row.user_id,
            token_expiry,
            settings,
        )
        download_url = f"{settings.api_prefix}/exports/{row.id}/download?token={token}"
    return {
        "requestId": row.id,
        "status": row.status,
        "createdAt": row.created_at,
        "startedAt": row.started_at,
        "completedAt": row.completed_at,
        "expiresAt": row.expires_at,
        "archiveSizeBytes": row.archive_size_bytes,
        "archiveSha256": row.archive_sha256,
        "downloadUrl": download_url,
        "failureCode": row.failure_code,
    }


def verify_export(
    row: DataExportRequest | None,
    *,
    export_id: UUID,
    token: str,
) -> bool:
    if row is None:
        return False
    now = utc_now()
    return bool(
        row.status == "ready"
        and row.archive_bytes is not None
        and row.expires_at is not None
        and row.expires_at > now
        and verify_export_download_token(
            token,
            export_id,
            row.user_id,
            now,
            taskiller_settings(),
        )
    )
