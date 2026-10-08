from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.core.config import Settings
from taskiller.core.idempotency import claim_idempotency, complete_idempotency
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import AuthSession, User, UserPreferences
from taskiller.execution.models import (
    ExecutionSessionModel,
    SessionEventModel,
    SessionReviewModel,
)
from taskiller.focus.models import (
    FocusPlanModel,
    FocusPlanRecommendationModel,
    FocusPlanSegmentModel,
)
from taskiller.operations.models import (
    AccountDeletionRequest,
    DataExportRequest,
    OutboxJob,
)
from taskiller.work.models import WorkItem, WorkType


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
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
        column.name: _json_value(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name not in omitted
    }


async def enqueue_job(
    db: AsyncSession,
    *,
    job_type: str,
    payload: dict[str, object],
    available_at: datetime | None = None,
    max_attempts: int = 5,
) -> OutboxJob:
    now = utc_now()
    job = OutboxJob(
        id=uuid4(),
        job_type=job_type,
        payload_json=payload,
        status="queued",
        available_at=available_at or now,
        locked_at=None,
        locked_by=None,
        lease_expires_at=None,
        attempts=0,
        max_attempts=max_attempts,
        last_error=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    db.add(job)
    return job


async def request_data_export(
    db: AsyncSession,
    *,
    user_id: UUID,
    idempotency_key: str,
    settings: Settings,
) -> tuple[DataExportRequest, bool]:
    replay = await claim_idempotency(
        db,
        owner_id=user_id,
        scope="data-export:create",
        key=idempotency_key,
        request_payload={},
        ttl_hours=settings.idempotency_ttl_hours,
    )
    if replay is not None and replay.resource_id is not None:
        existing = await db.get(DataExportRequest, replay.resource_id)
        if existing is None:
            raise ApiError(409, "idempotency_replay_missing", "Export replay unavailable")
        return existing, True

    now = utc_now()
    export = DataExportRequest(
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
    db.add(export)
    await db.flush()
    await enqueue_job(
        db,
        job_type="data_export",
        payload={"exportRequestId": str(export.id), "userId": str(user_id)},
        max_attempts=settings.outbox_max_attempts,
    )
    await complete_idempotency(
        db,
        owner_id=user_id,
        scope="data-export:create",
        key=idempotency_key,
        response_status=202,
        response_body={"requestId": str(export.id), "status": "queued"},
        resource_id=export.id,
    )
    await db.commit()
    return export, False


async def schedule_account_deletion(
    db: AsyncSession,
    *,
    user: User,
    settings: Settings,
) -> AccountDeletionRequest:
    now = utc_now()
    existing = (
        await db.execute(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    execute_after = now + timedelta(days=settings.account_deletion_grace_days)
    request = AccountDeletionRequest(
        id=uuid4(),
        user_id=user.id,
        status="scheduled",
        requested_at=now,
        execute_after=execute_after,
        started_at=None,
        completed_at=None,
        failure_code=None,
    )
    db.add(request)
    sessions = list(
        (
            await db.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .with_for_update()
            )
        ).all()
    )
    for auth_session in sessions:
        auth_session.revoked_at = now
        auth_session.revocation_reason = "account_deletion_scheduled"
    user.is_active = False
    user.version += 1
    user.updated_at = now
    await enqueue_job(
        db,
        job_type="account_delete",
        payload={"requestId": str(request.id), "userId": str(user.id)},
        available_at=execute_after,
        max_attempts=settings.outbox_max_attempts,
    )
    await db.commit()
    return request


async def build_export_archive(
    db: AsyncSession, export: DataExportRequest, settings: Settings
) -> None:
    user = await db.get(User, export.user_id)
    if user is None:
        raise RuntimeError("export user no longer exists")
    preferences = await db.get(UserPreferences, export.user_id)

    async def rows(model: Any, criterion: Any) -> list[dict[str, Any]]:
        result = list((await db.scalars(select(model).where(criterion))).all())
        return [_model_dict(item) for item in result]

    work_types = list(
        (
            await db.scalars(
                select(WorkType).where(
                    (WorkType.owner_id == export.user_id) | WorkType.owner_id.is_(None)
                )
            )
        ).all()
    )
    work_items = await rows(WorkItem, WorkItem.owner_id == export.user_id)
    recommendations = await rows(
        FocusPlanRecommendationModel,
        FocusPlanRecommendationModel.owner_id == export.user_id,
    )
    plans = await rows(FocusPlanModel, FocusPlanModel.owner_id == export.user_id)
    plan_ids = [UUID(item["id"]) for item in plans]
    segments: list[dict[str, Any]] = []
    if plan_ids:
        segments = [
            _model_dict(item)
            for item in (
                await db.scalars(
                    select(FocusPlanSegmentModel).where(
                        FocusPlanSegmentModel.focus_plan_id.in_(plan_ids)
                    )
                )
            ).all()
        ]
    sessions = await rows(ExecutionSessionModel, ExecutionSessionModel.owner_id == export.user_id)
    events = await rows(SessionEventModel, SessionEventModel.owner_id == export.user_id)
    reviews = await rows(SessionReviewModel, SessionReviewModel.owner_id == export.user_id)

    payload = {
        "format": "taskiller-data-export-v1",
        "generatedAt": utc_now().isoformat(),
        "user": _model_dict(user, exclude={"password_hash"}),
        "preferences": _model_dict(preferences) if preferences is not None else None,
        "workTypes": [_model_dict(item) for item in work_types],
        "workItems": work_items,
        "focusPlanRecommendations": recommendations,
        "focusPlans": plans,
        "focusPlanSegments": segments,
        "executionSessions": sessions,
        "sessionEvents": events,
        "sessionReviews": reviews,
        "excludedSecrets": [
            "passwordHash",
            "refreshTokens",
            "emailVerificationTokens",
            "passwordResetTokens",
            "rateLimitBuckets",
            "internalOutboxJobs",
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    archive = gzip.compress(raw, compresslevel=6)
    now = utc_now()
    export.archive_bytes = archive
    export.archive_sha256 = hashlib.sha256(archive).hexdigest()
    export.archive_size_bytes = len(archive)
    export.status = "ready"
    export.completed_at = now
    export.expires_at = now + timedelta(hours=settings.export_ttl_hours)
    export.failure_code = None


async def hard_delete_account(db: AsyncSession, request: AccountDeletionRequest) -> None:
    request.status = "processing"
    request.started_at = request.started_at or utc_now()
    await db.flush()
    # Delete RESTRICT-linked execution/history before the self-referential Work tree.
    await db.execute(
        delete(ExecutionSessionModel).where(ExecutionSessionModel.owner_id == request.user_id)
    )
    for kind in ("chore", "sprint", "project"):
        await db.execute(
            delete(WorkItem).where(WorkItem.owner_id == request.user_id, WorkItem.kind == kind)
        )
    await db.execute(delete(User).where(User.id == request.user_id))
    request.status = "completed"
    request.completed_at = utc_now()
    request.failure_code = None
