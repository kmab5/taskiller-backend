from __future__ import annotations

from datetime import datetime
from uuid import UUID

from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.analytics.schemas import AnalyticsBucket
from taskiller.django_api.analytics_service import DjangoAnalyticsService
from taskiller.django_api.errors import TaskillerAPIError


def _service(request: Request) -> DjangoAnalyticsService:
    return DjangoAnalyticsService(owner_id=request.auth.user.id)


def _required_datetime(request: Request, name: str) -> datetime:
    raw = request.query_params.get(name)
    if not raw:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            f"{name} is required.",
        )
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            f"{name} must be a valid datetime.",
        ) from exc


def _json(value: object) -> dict[str, object]:
    return value.model_dump(mode="json", by_alias=True)  # type: ignore[attr-defined]


class AnalyticsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getAnalyticsSummary",
        tags=["Analytics"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        result = async_to_sync(_service(request).summary)(
            _required_datetime(request, "from"),
            _required_datetime(request, "to"),
        )
        return Response(_json(result))


class WorkTypeAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getWorkTypeAnalytics",
        tags=["Analytics"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        result = async_to_sync(_service(request).work_types)(
            _required_datetime(request, "from"),
            _required_datetime(request, "to"),
        )
        return Response(_json(result))


class WorkItemAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getWorkItemAnalytics",
        tags=["Analytics"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, workItemId: UUID) -> Response:
        result = async_to_sync(_service(request).work_item)(
            workItemId,
            _required_datetime(request, "from"),
            _required_datetime(request, "to"),
        )
        return Response(_json(result))


class AnalyticsTimeseriesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getAnalyticsTimeseries",
        tags=["Analytics"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("bucket")
        try:
            bucket = AnalyticsBucket(raw)
        except (TypeError, ValueError) as exc:
            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "bucket must be day or week.",
            ) from exc
        result = async_to_sync(_service(request).timeseries)(
            _required_datetime(request, "from"),
            _required_datetime(request, "to"),
            bucket,
        )
        return Response(_json(result))


class FocusPatternsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getFocusPatterns",
        tags=["Analytics"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        result = async_to_sync(_service(request).focus_patterns)(
            _required_datetime(request, "from"),
            _required_datetime(request, "to"),
        )
        return Response(_json(result))
