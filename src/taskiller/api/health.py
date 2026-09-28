from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/health", tags=["Operations"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]


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
        await request.app.state.database.healthcheck()
    except (SQLAlchemyError, OSError):
        payload = ReadinessResponse(status="not_ready", database="unavailable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
    return ReadinessResponse(status="ready", database="ok")
