from __future__ import annotations

from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_api.work_service import (
    DjangoWorkService,
    require_idempotency_key,
    validate_payload,
)
from taskiller.users.etag import make_etag
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    CreateWorkTypeRequest,
    ReorderWorkItemRequest,
    UpdateWorkItemRequest,
    UpdateWorkTypeRequest,
    WorkItemKind,
    WorkItemStatus,
)


def _service(request: Request) -> DjangoWorkService:
    return DjangoWorkService(request.auth.user.id)


def _etag(response: Response, kind: str, item: dict[str, object]) -> None:
    response["ETag"] = make_etag(
        kind,
        UUID(str(item["id"])),
        int(item["version"]),
    )


def _parse_uuid(value: str | None, name: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        from taskiller.django_api.errors import TaskillerAPIError

        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            f"{name} must be a valid UUID.",
        ) from exc


class WorkTypesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listWorkTypes",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        return Response(_service(request).list_work_types())

    @extend_schema(
        operation_id="createWorkType",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        payload = validate_payload(CreateWorkTypeRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        item = _service(request).create_work_type(payload, key)
        response = Response(item, status=201)
        _etag(response, "work-type", item)
        response["Location"] = f"{taskiller_settings().api_prefix}/work-types/{item['id']}"
        return response


class WorkTypeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getWorkType",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        workTypeId: UUID,
    ) -> Response:
        item = _service(request).get_work_type(workTypeId)
        response = Response(item)
        _etag(response, "work-type", item)
        return response

    @extend_schema(
        operation_id="updateWorkType",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(
        self,
        request: Request,
        workTypeId: UUID,
    ) -> Response:
        payload = validate_payload(UpdateWorkTypeRequest, request.data)
        item = _service(request).update_work_type(
            workTypeId,
            payload,
            request.headers.get("If-Match"),
        )
        response = Response(item)
        _etag(response, "work-type", item)
        return response

    @extend_schema(
        operation_id="deleteWorkType",
        tags=["Work"],
        responses={204: None},
    )
    def delete(
        self,
        request: Request,
        workTypeId: UUID,
    ) -> Response:
        _service(request).delete_work_type(
            workTypeId,
            request.headers.get("If-Match"),
        )
        return Response(status=204)


class WorkItemsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listWorkItems",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", "25"))
        except ValueError:
            limit = 0
        if not 1 <= limit <= 100:
            from taskiller.django_api.errors import TaskillerAPIError

            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "limit must be between 1 and 100.",
            )

        kind_value = request.query_params.get("kind")
        status_value = request.query_params.get("status")
        try:
            kind = WorkItemKind(kind_value) if kind_value else None
            status = WorkItemStatus(status_value) if status_value else None
        except ValueError as exc:
            from taskiller.django_api.errors import TaskillerAPIError

            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "One or more query values are invalid.",
            ) from exc

        include_deleted = request.query_params.get("includeDeleted", "false").casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        parent_id = _parse_uuid(
            request.query_params.get("parentId"),
            "parentId",
        )

        return Response(
            _service(request).list_work_items(
                limit=limit,
                cursor=request.query_params.get("cursor"),
                kind=kind,
                status=status,
                parent_id=parent_id,
                include_deleted=include_deleted,
            )
        )

    @extend_schema(
        operation_id="createWorkItem",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        payload = validate_payload(CreateWorkItemRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        item = _service(request).create_work_item(payload, key)
        response = Response(item, status=201)
        _etag(response, "work-item", item)
        response["Location"] = f"{taskiller_settings().api_prefix}/work-items/{item['id']}"
        return response


class WorkItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getWorkItem",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        item = _service(request).get_work_item(workItemId)
        response = Response(item)
        _etag(response, "work-item", item)
        return response

    @extend_schema(
        operation_id="updateWorkItem",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def patch(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        payload = validate_payload(UpdateWorkItemRequest, request.data)
        item = _service(request).update_work_item(
            workItemId,
            payload,
            request.headers.get("If-Match"),
        )
        response = Response(item)
        _etag(response, "work-item", item)
        return response

    @extend_schema(
        operation_id="deleteWorkItem",
        tags=["Work"],
        responses={204: None},
    )
    def delete(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        _service(request).delete_work_item(
            workItemId,
            request.headers.get("If-Match"),
        )
        return Response(status=204)


class WorkItemChildrenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listWorkItemChildren",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        return Response(_service(request).list_children(workItemId))


class WorkItemTreeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getWorkItemTree",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        return Response(_service(request).get_tree(workItemId))


class WorkItemReorderView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="reorderWorkItem",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(
        self,
        request: Request,
        workItemId: UUID,
    ) -> Response:
        payload = validate_payload(ReorderWorkItemRequest, request.data)
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        item = _service(request).reorder_work_item(
            workItemId,
            payload,
            request.headers.get("If-Match"),
            key,
        )
        response = Response(item)
        _etag(response, "work-item", item)
        return response


class ProjectNextActionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getProjectNextAction",
        tags=["Work"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(
        self,
        request: Request,
        projectId: UUID,
    ) -> Response:
        return Response(_service(request).get_project_next_action(projectId))
