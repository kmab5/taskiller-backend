from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response, status
from fastapi.responses import Response as RawResponse
from sqlalchemy import select

from taskiller.auth.dependencies import CurrentAuth
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.dependencies import DbSession
from taskiller.db.models import User
from taskiller.operations.models import DataExportRequest
from taskiller.operations.schemas import AccountDeletionResponse, DataExportResponse, ExportStatus
from taskiller.operations.security import enforce_rate_limit, record_security_event, request_subject
from taskiller.operations.service import request_data_export, schedule_account_deletion
from taskiller.operations.tokens import create_export_download_token, verify_export_download_token
from taskiller.users.etag import make_etag, require_etag

router = APIRouter(tags=["User"])


def _export_response(row: DataExportRequest, request: Request) -> DataExportResponse:
    download_url = None
    now = utc_now()
    if row.status == "ready" and row.expires_at is not None and row.expires_at > now:
        token_expiry = min(
            row.expires_at,
            now + timedelta(seconds=request.app.state.settings.export_download_ttl_seconds),
        )
        token = create_export_download_token(
            row.id, row.user_id, token_expiry, request.app.state.settings
        )
        download_url = (
            f"{request.app.state.settings.api_prefix}/exports/{row.id}/download?token={token}"
        )
    return DataExportResponse(
        request_id=row.id,
        status=ExportStatus(row.status),
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        expires_at=row.expires_at,
        archive_size_bytes=row.archive_size_bytes,
        archive_sha256=row.archive_sha256,
        download_url=download_url,
        failure_code=row.failure_code,
    )


@router.post(
    "/me/export-requests",
    response_model=DataExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestDataExport",
)
async def create_export(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> DataExportResponse:
    await enforce_rate_limit(
        request,
        scope="data_export",
        subject=request_subject(request, str(auth.user.id)),
        limit=request.app.state.settings.export_request_limit,
        window_seconds=request.app.state.settings.export_request_window_seconds,
    )
    row, _ = await request_data_export(
        db,
        user_id=auth.user.id,
        idempotency_key=idempotency_key,
        settings=request.app.state.settings,
    )
    await record_security_event(request, event_type="data_export_requested", user_id=auth.user.id)
    return _export_response(row, request)


@router.get(
    "/me/export-requests/{exportRequestId}",
    response_model=DataExportResponse,
    operation_id="getDataExportRequest",
)
async def get_export(
    export_id: Annotated[UUID, Path(alias="exportRequestId")],
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> DataExportResponse:
    row = (
        await db.execute(
            select(DataExportRequest).where(
                DataExportRequest.id == export_id,
                DataExportRequest.user_id == auth.user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "data_export_not_found", "Data export not found")
    return _export_response(row, request)


@router.get(
    "/exports/{exportRequestId}/download",
    response_class=RawResponse,
    operation_id="downloadDataExport",
)
async def download_export(
    export_id: Annotated[UUID, Path(alias="exportRequestId")],
    token: Annotated[str, Query(min_length=20)],
    request: Request,
    db: DbSession,
) -> RawResponse:
    row = await db.get(DataExportRequest, export_id)
    now = utc_now()
    if (
        row is None
        or row.status != "ready"
        or row.archive_bytes is None
        or row.expires_at is None
        or row.expires_at <= now
        or not verify_export_download_token(
            token, export_id, row.user_id, now, request.app.state.settings
        )
    ):
        raise ApiError(404, "data_export_not_found", "Data export not found")
    return RawResponse(
        content=row.archive_bytes,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="taskiller-export-{export_id}.json.gz"',
            "Cache-Control": "private, no-store",
            "Digest": f"sha-256={row.archive_sha256}",
        },
    )


@router.delete(
    "/me",
    response_model=AccountDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestAccountDeletion",
)
async def request_account_deletion(
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AccountDeletionResponse:
    await enforce_rate_limit(
        request,
        scope="account_delete",
        subject=request_subject(request, str(auth.user.id)),
        limit=2,
        window_seconds=3600,
    )
    user = (
        await db.execute(
            select(User)
            .where(User.id == auth.user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    require_etag(if_match, make_etag("user", user.id, user.version))
    deletion = await schedule_account_deletion(db, user=user, settings=request.app.state.settings)
    await record_security_event(
        request,
        event_type="account_deletion_scheduled",
        user_id=user.id,
        metadata={"requestId": str(deletion.id)},
    )
    response.headers["Clear-Site-Data"] = '"cookies", "storage"'
    return AccountDeletionResponse(
        request_id=deletion.id,
        status=deletion.status,
        requested_at=deletion.requested_at,
        execute_after=deletion.execute_after,
    )
