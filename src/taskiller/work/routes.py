from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Header,
    Path as ApiPath,
    Query,
    Request,
    Response,
    status as http_status,
)

from taskiller.auth.dependencies import CurrentAuth
from taskiller.db.dependencies import DbSession
from taskiller.users.etag import make_etag
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    CreateWorkTypeRequest,
    ProjectNextActionResponse,
    ReorderWorkItemRequest,
    UpdateWorkItemRequest,
    UpdateWorkTypeRequest,
    WorkItemChildrenResponse,
    WorkItemKind,
    WorkItemPage,
    WorkItemResponse,
    WorkItemStatus,
    WorkItemTreeNode,
    WorkTypeListResponse,
    WorkTypeResponse,
)
from taskiller.work.service import WorkService

router = APIRouter(tags=["Work"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
WorkTypeId = Annotated[UUID, ApiPath(alias="workTypeId")]
WorkItemId = Annotated[UUID, ApiPath(alias="workItemId")]
ProjectId = Annotated[UUID, ApiPath(alias="projectId")]


def _service(request: Request, db: DbSession, auth: CurrentAuth) -> WorkService:
    return WorkService(
        db,
        owner_id=auth.user.id,
        idempotency_ttl_hours=request.app.state.settings.idempotency_ttl_hours,
    )


def _work_type_etag(response: Response, item: WorkTypeResponse) -> None:
    response.headers["ETag"] = make_etag("work-type", item.id, item.version)


def _work_item_etag(response: Response, item: WorkItemResponse) -> None:
    response.headers["ETag"] = make_etag("work-item", item.id, item.version)


@router.get("/work-types", response_model=WorkTypeListResponse, operation_id="listWorkTypes")
async def list_work_types(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> WorkTypeListResponse:
    return await _service(request, db, auth).list_work_types()


@router.post(
    "/work-types",
    response_model=WorkTypeResponse,
    status_code=http_status.HTTP_201_CREATED,
    operation_id="createWorkType",
)
async def create_work_type(
    payload: CreateWorkTypeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> WorkTypeResponse:
    item = await _service(request, db, auth).create_work_type(payload, idempotency_key)
    _work_type_etag(response, item)
    response.headers["Location"] = f"{request.app.state.settings.api_prefix}/work-types/{item.id}"
    return item


@router.get(
    "/work-types/{workTypeId}",
    response_model=WorkTypeResponse,
    operation_id="getWorkType",
)
async def get_work_type(
    work_type_id: WorkTypeId,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> WorkTypeResponse:
    item = await _service(request, db, auth).get_work_type(work_type_id)
    _work_type_etag(response, item)
    return item


@router.patch(
    "/work-types/{workTypeId}",
    response_model=WorkTypeResponse,
    operation_id="updateWorkType",
)
async def update_work_type(
    work_type_id: WorkTypeId,
    payload: UpdateWorkTypeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> WorkTypeResponse:
    item = await _service(request, db, auth).update_work_type(work_type_id, payload, if_match)
    _work_type_etag(response, item)
    return item


@router.delete(
    "/work-types/{workTypeId}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    operation_id="deleteWorkType",
)
async def delete_work_type(
    work_type_id: WorkTypeId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> Response:
    await _service(request, db, auth).delete_work_type(work_type_id, if_match)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get("/work-items", response_model=WorkItemPage, operation_id="listWorkItems")
async def list_work_items(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    kind: WorkItemKind | None = None,
    item_status: Annotated[WorkItemStatus | None, Query(alias="status")] = None,
    parent_id: Annotated[UUID | None, Query(alias="parentId")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> WorkItemPage:
    return await _service(request, db, auth).list_work_items(
        limit=limit,
        cursor=cursor,
        kind=kind,
        status=item_status,
        parent_id=parent_id,
        include_deleted=include_deleted,
    )


@router.post(
    "/work-items",
    response_model=WorkItemResponse,
    status_code=http_status.HTTP_201_CREATED,
    operation_id="createWorkItem",
)
async def create_work_item(
    payload: CreateWorkItemRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> WorkItemResponse:
    item = await _service(request, db, auth).create_work_item(payload, idempotency_key)
    _work_item_etag(response, item)
    response.headers["Location"] = f"{request.app.state.settings.api_prefix}/work-items/{item.id}"
    return item


@router.get(
    "/work-items/{workItemId}",
    response_model=WorkItemResponse,
    operation_id="getWorkItem",
)
async def get_work_item(
    work_item_id: WorkItemId,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> WorkItemResponse:
    item = await _service(request, db, auth).get_work_item(work_item_id)
    _work_item_etag(response, item)
    return item


@router.patch(
    "/work-items/{workItemId}",
    response_model=WorkItemResponse,
    operation_id="updateWorkItem",
)
async def update_work_item(
    work_item_id: WorkItemId,
    payload: UpdateWorkItemRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> WorkItemResponse:
    item = await _service(request, db, auth).update_work_item(work_item_id, payload, if_match)
    _work_item_etag(response, item)
    return item


@router.delete(
    "/work-items/{workItemId}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    operation_id="deleteWorkItem",
)
async def delete_work_item(
    work_item_id: WorkItemId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> Response:
    await _service(request, db, auth).delete_work_item(work_item_id, if_match)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get(
    "/work-items/{workItemId}/children",
    response_model=WorkItemChildrenResponse,
    operation_id="listWorkItemChildren",
)
async def list_work_item_children(
    work_item_id: WorkItemId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> WorkItemChildrenResponse:
    return await _service(request, db, auth).list_children(work_item_id)


@router.get(
    "/work-items/{workItemId}/tree",
    response_model=WorkItemTreeNode,
    operation_id="getWorkItemTree",
)
async def get_work_item_tree(
    work_item_id: WorkItemId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> WorkItemTreeNode:
    return await _service(request, db, auth).get_tree(work_item_id)


@router.post(
    "/work-items/{workItemId}/reorder",
    response_model=WorkItemResponse,
    operation_id="reorderWorkItem",
)
async def reorder_work_item(
    work_item_id: WorkItemId,
    payload: ReorderWorkItemRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> WorkItemResponse:
    item = await _service(request, db, auth).reorder_work_item(
        work_item_id,
        payload,
        if_match,
        idempotency_key,
    )
    _work_item_etag(response, item)
    return item


@router.get(
    "/projects/{projectId}/next-action",
    response_model=ProjectNextActionResponse,
    operation_id="getProjectNextAction",
)
async def get_project_next_action(
    project_id: ProjectId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> ProjectNextActionResponse:
    return await _service(request, db, auth).get_project_next_action(project_id)
