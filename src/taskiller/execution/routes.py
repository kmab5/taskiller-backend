from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response, status

from taskiller.auth.dependencies import CurrentAuth
from taskiller.db.dependencies import DbSession
from taskiller.execution.schemas import (
    ActiveExecutionSession,
    AppendSessionEventResponse,
    CreateSessionEventRequest,
    ExecutionSession,
    ExecutionSessionPage,
    ExecutionSessionState,
    SessionEventPage,
    SessionReview,
    StartExecutionSessionRequest,
    UpsertSessionReviewRequest,
)
from taskiller.execution.service import ExecutionService
from taskiller.users.etag import make_etag

router = APIRouter(prefix="/execution-sessions", tags=["Execution"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
ExecutionSessionId = Annotated[UUID, Path(alias="executionSessionId")]


def _service(request: Request, db: DbSession, auth: CurrentAuth) -> ExecutionService:
    return ExecutionService(
        db,
        owner_id=auth.user.id,
        idempotency_ttl_hours=request.app.state.settings.idempotency_ttl_hours,
    )


def _session_etag(response: Response, session: ExecutionSession) -> None:
    response.headers["ETag"] = make_etag("execution-session", session.id, session.version)


def _review_etag(response: Response, review: SessionReview) -> None:
    response.headers["ETag"] = make_etag("session-review", review.session_id, review.version)


@router.get("", response_model=ExecutionSessionPage, operation_id="listExecutionSessions")
async def list_execution_sessions(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    work_item_id: Annotated[UUID | None, Query(alias="workItemId")] = None,
    state: ExecutionSessionState | None = None,
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
) -> ExecutionSessionPage:
    return await _service(request, db, auth).list_sessions(
        limit=limit,
        cursor=cursor,
        work_item_id=work_item_id,
        state=state,
        from_at=from_at,
        to_at=to_at,
    )


@router.post(
    "",
    response_model=ExecutionSession,
    status_code=status.HTTP_201_CREATED,
    operation_id="startExecutionSession",
)
async def start_execution_session(
    payload: StartExecutionSessionRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> ExecutionSession:
    session = await _service(request, db, auth).start_session(payload, idempotency_key)
    _session_etag(response, session)
    response.headers["Location"] = (
        f"{request.app.state.settings.api_prefix}/execution-sessions/{session.id}"
    )
    return session


@router.get(
    "/active",
    response_model=ActiveExecutionSession,
    operation_id="getActiveExecutionSession",
)
async def get_active_execution_session(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> ActiveExecutionSession:
    return await _service(request, db, auth).get_active_session()


@router.get(
    "/{executionSessionId}",
    response_model=ExecutionSession,
    operation_id="getExecutionSession",
)
async def get_execution_session(
    execution_session_id: ExecutionSessionId,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> ExecutionSession:
    session = await _service(request, db, auth).get_session(execution_session_id)
    _session_etag(response, session)
    return session


@router.get(
    "/{executionSessionId}/events",
    response_model=SessionEventPage,
    operation_id="listExecutionSessionEvents",
)
async def list_execution_session_events(
    execution_session_id: ExecutionSessionId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> SessionEventPage:
    return await _service(request, db, auth).list_events(
        execution_session_id, limit=limit, cursor=cursor
    )


@router.post(
    "/{executionSessionId}/events",
    response_model=AppendSessionEventResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="appendExecutionSessionEvent",
)
async def append_execution_session_event(
    execution_session_id: ExecutionSessionId,
    payload: CreateSessionEventRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> AppendSessionEventResponse:
    result = await _service(request, db, auth).append_event(
        execution_session_id,
        payload,
        idempotency_key,
        if_match,
    )
    _session_etag(response, result.session)
    return result


@router.get(
    "/{executionSessionId}/review",
    response_model=SessionReview,
    operation_id="getExecutionSessionReview",
)
async def get_execution_session_review(
    execution_session_id: ExecutionSessionId,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> SessionReview:
    review = await _service(request, db, auth).get_review(execution_session_id)
    _review_etag(response, review)
    return review


@router.put(
    "/{executionSessionId}/review",
    response_model=SessionReview,
    operation_id="upsertExecutionSessionReview",
)
async def upsert_execution_session_review(
    execution_session_id: ExecutionSessionId,
    payload: UpsertSessionReviewRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> SessionReview:
    review = await _service(request, db, auth).upsert_review(
        execution_session_id, payload, idempotency_key
    )
    _review_etag(response, review)
    return review
