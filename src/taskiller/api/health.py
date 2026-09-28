from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from taskiller import __version__
from taskiller.core.runtime import build_metadata

router = APIRouter(prefix="/health", tags=["Operations"])
EXPECTED_DB_REVISION = "20260928_0006"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]
    migration: Literal["ok", "out_of_date", "unavailable"]
    expected_revision: str
    current_revision: str | None


class VersionResponse(BaseModel):
    version: str
    release_sha: str | None
    release_branch: str | None
    release_repository: str | None


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    operation_id="healthLive",
)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    summary="Readiness probe",
    operation_id="healthReady",
)
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    try:
        current_revision = await request.app.state.database.healthcheck()
    except (SQLAlchemyError, OSError):
        payload = ReadinessResponse(
            status="not_ready",
            database="unavailable",
            migration="unavailable",
            expected_revision=EXPECTED_DB_REVISION,
            current_revision=None,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
    if current_revision != EXPECTED_DB_REVISION:
        payload = ReadinessResponse(
            status="not_ready",
            database="ok",
            migration="out_of_date",
            expected_revision=EXPECTED_DB_REVISION,
            current_revision=current_revision,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
    return ReadinessResponse(
        status="ready",
        database="ok",
        migration="ok",
        expected_revision=EXPECTED_DB_REVISION,
        current_revision=current_revision,
    )


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Build version",
    operation_id="healthVersion",
)
async def version() -> VersionResponse:
    metadata = build_metadata()
    return VersionResponse(
        version=__version__,
        release_sha=metadata.release_sha,
        release_branch=metadata.release_branch,
        release_repository=metadata.release_repository,
    )
