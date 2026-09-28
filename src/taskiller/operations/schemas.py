from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from taskiller.api.models import ApiModel


class ExportStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DataExportResponse(ApiModel):
    request_id: UUID
    status: ExportStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    archive_size_bytes: int | None
    archive_sha256: str | None
    download_url: str | None
    failure_code: str | None


class AccountDeletionResponse(ApiModel):
    request_id: UUID
    status: str
    requested_at: datetime
    execute_after: datetime
