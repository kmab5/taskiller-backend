from __future__ import annotations

from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.django_api.focus_service import (
    DjangoFocusService,
    require_idempotency_key,
    validate_payload,
)
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.runtime import taskiller_settings
from taskiller.focus.schemas import (
    CreateFocusPlanRequest,
    CreateRecommendationRequest,
    UpdateFocusPlanRequest,
)
from taskiller.users.etag import make_etag


def _service(request: Request) -> DjangoFocusService:
    return DjangoFocusService(request.auth.user.id)


def _etag(response: Response, item: dict[str, object]) -> None:
    response["ETag"] = make_etag(
        "focus-plan",
        UUID(str(item["id"])),
        int(item["version"]),
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


class RecommendationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="createFocusPlanRecommendation",
        tags=["Focus"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        payload = validate_payload(CreateRecommendationRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        return Response(
            _service(request).create_recommendation(payload, key),
            status=201,
        )


class RecommendationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getFocusPlanRecommendation",
        tags=["Focus"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, recommendationId: UUID) -> Response:
        return Response(_service(request).get_recommendation(recommendationId))


class FocusPlansView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listFocusPlans",
        tags=["Focus"],
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
        template_only = request.query_params.get("templateOnly", "false").casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        work_item_id = _parse_uuid(
            request.query_params.get("workItemId"),
            "workItemId",
        )
        return Response(
            _service(request).list_focus_plans(
                limit=limit,
                cursor=request.query_params.get("cursor"),
                work_item_id=work_item_id,
                template_only=template_only,
            )
        )

    @extend_schema(
        operation_id="createFocusPlan",
        tags=["Focus"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        payload = validate_payload(CreateFocusPlanRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        plan = _service(request).create_focus_plan(payload, key)
        response = Response(plan, status=201)
        _etag(response, plan)
        response["Location"] = f"{taskiller_settings().api_prefix}/focus-plans/{plan['id']}"
        return response


class FocusPlanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getFocusPlan",
        tags=["Focus"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, focusPlanId: UUID) -> Response:
        plan = _service(request).get_focus_plan(focusPlanId)
        response = Response(plan)
        _etag(response, plan)
        return response

    @extend_schema(
        operation_id="updateFocusPlan",
        tags=["Focus"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(self, request: Request, focusPlanId: UUID) -> Response:
        payload = validate_payload(UpdateFocusPlanRequest, request.data)
        plan = _service(request).update_focus_plan(
            focusPlanId,
            payload,
            request.headers.get("If-Match"),
        )
        response = Response(plan)
        _etag(response, plan)
        return response

    @extend_schema(
        operation_id="deleteFocusPlan",
        tags=["Focus"],
        responses={204: None},
    )
    def delete(self, request: Request, focusPlanId: UUID) -> Response:
        _service(request).delete_focus_plan(
            focusPlanId,
            request.headers.get("If-Match"),
        )
        return Response(status=204)
