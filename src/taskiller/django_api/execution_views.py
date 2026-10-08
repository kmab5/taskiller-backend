from __future__ import annotations

from datetime import datetime
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.execution_service import (
    DjangoExecutionService,
    require_idempotency_key,
    validate_payload,
)
from taskiller.django_api.runtime import taskiller_settings
from taskiller.execution.schemas import (
    CreateSessionEventRequest,
    ExecutionSessionState,
    StartExecutionSessionRequest,
    UpsertSessionReviewRequest,
)
from taskiller.users.etag import make_etag


def _service(request: Request) -> DjangoExecutionService:
    return DjangoExecutionService(request.auth.user.id)


def _session_etag(response: Response, session: dict[str, object]) -> None:
    response["ETag"] = make_etag(
        "execution-session",
        UUID(str(session["id"])),
        int(session["version"]),
    )


def _review_etag(response: Response, review: dict[str, object]) -> None:
    response["ETag"] = make_etag(
        "session-review",
        UUID(str(review["sessionId"])),
        int(review["version"]),
    )


def _parse_uuid(value: str | None, name: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            f"{name} must be a valid UUID.",
        ) from exc


def _parse_datetime(value: str | None, name: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            f"{name} must be a valid datetime.",
        ) from exc


class ExecutionSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listExecutionSessions",
        tags=["Execution"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", "25"))
        except ValueError:
            limit = 0
        if not 1 <= limit <= 100:
            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "limit must be between 1 and 100.",
            )

        state_value = request.query_params.get("state")
        try:
            state = ExecutionSessionState(state_value) if state_value else None
        except ValueError as exc:
            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "state is invalid.",
            ) from exc

        return Response(
            _service(request).list_sessions(
                limit=limit,
                cursor=request.query_params.get("cursor"),
                work_item_id=_parse_uuid(
                    request.query_params.get("workItemId"),
                    "workItemId",
                ),
                state=state,
                from_at=_parse_datetime(
                    request.query_params.get("from"),
                    "from",
                ),
                to_at=_parse_datetime(
                    request.query_params.get("to"),
                    "to",
                ),
            )
        )

    @extend_schema(
        operation_id="startExecutionSession",
        tags=["Execution"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        payload = validate_payload(StartExecutionSessionRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        session = _service(request).start_session(payload, key)
        response = Response(session, status=201)
        _session_etag(response, session)
        response["Location"] = (
            f"{taskiller_settings().api_prefix}/execution-sessions/{session['id']}"
        )
        return response


class ActiveExecutionSessionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getActiveExecutionSession",
        tags=["Execution"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        return Response(_service(request).get_active_session())


class ExecutionSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getExecutionSession",
        tags=["Execution"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        executionSessionId: UUID,
    ) -> Response:
        session = _service(request).get_session(executionSessionId)
        response = Response(session)
        _session_etag(response, session)
        return response


class ExecutionSessionEventsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listExecutionSessionEvents",
        tags=["Execution"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        executionSessionId: UUID,
    ) -> Response:
        try:
            limit = int(request.query_params.get("limit", "25"))
        except ValueError:
            limit = 0
        if not 1 <= limit <= 100:
            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "limit must be between 1 and 100.",
            )
        return Response(
            _service(request).list_events(
                executionSessionId,
                limit=limit,
                cursor=request.query_params.get("cursor"),
            )
        )

    @extend_schema(
        operation_id="appendExecutionSessionEvent",
        tags=["Execution"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(
        self,
        request: Request,
        executionSessionId: UUID,
    ) -> Response:
        payload = validate_payload(CreateSessionEventRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        result = _service(request).append_event(
            executionSessionId,
            payload,
            key,
            request.headers.get("If-Match"),
        )
        response = Response(result, status=201)
        _session_etag(response, result["session"])
        return response


class ExecutionSessionReviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getExecutionSessionReview",
        tags=["Execution"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        executionSessionId: UUID,
    ) -> Response:
        review = _service(request).get_review(executionSessionId)
        response = Response(review)
        _review_etag(response, review)
        return response

    @extend_schema(
        operation_id="upsertExecutionSessionReview",
        tags=["Execution"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def put(
        self,
        request: Request,
        executionSessionId: UUID,
    ) -> Response:
        payload = validate_payload(
            UpsertSessionReviewRequest,
            request.data,
        )
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        review = _service(request).upsert_review(
            executionSessionId,
            payload,
            key,
        )
        response = Response(review)
        _review_etag(response, review)
        return response
