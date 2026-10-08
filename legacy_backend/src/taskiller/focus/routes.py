from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response, status

from taskiller.auth.dependencies import CurrentAuth
from taskiller.db.dependencies import DbSession
from taskiller.focus.schemas import (
    CreateFocusPlanRequest,
    CreateRecommendationRequest,
    FocusPlan,
    FocusPlanPage,
    FocusPlanRecommendation,
    UpdateFocusPlanRequest,
)
from taskiller.focus.service import FocusService
from taskiller.users.etag import make_etag

router = APIRouter(tags=["Focus"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
RecommendationId = Annotated[UUID, Path(alias="recommendationId")]
FocusPlanId = Annotated[UUID, Path(alias="focusPlanId")]


def _service(request: Request, db: DbSession, auth: CurrentAuth) -> FocusService:
    return FocusService(
        db,
        owner_id=auth.user.id,
        idempotency_ttl_hours=request.app.state.settings.idempotency_ttl_hours,
    )


def _focus_plan_etag(response: Response, plan: FocusPlan) -> None:
    response.headers["ETag"] = make_etag("focus-plan", plan.id, plan.version)


@router.post(
    "/focus-plan-recommendations",
    response_model=FocusPlanRecommendation,
    status_code=status.HTTP_201_CREATED,
    operation_id="createFocusPlanRecommendation",
)
async def create_focus_plan_recommendation(
    payload: CreateRecommendationRequest,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> FocusPlanRecommendation:
    return await _service(request, db, auth).create_recommendation(payload, idempotency_key)


@router.get(
    "/focus-plan-recommendations/{recommendationId}",
    response_model=FocusPlanRecommendation,
    operation_id="getFocusPlanRecommendation",
)
async def get_focus_plan_recommendation(
    recommendation_id: RecommendationId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> FocusPlanRecommendation:
    return await _service(request, db, auth).get_recommendation(recommendation_id)


@router.get(
    "/focus-plans",
    response_model=FocusPlanPage,
    operation_id="listFocusPlans",
)
async def list_focus_plans(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    work_item_id: Annotated[UUID | None, Query(alias="workItemId")] = None,
    template_only: Annotated[bool, Query(alias="templateOnly")] = False,
) -> FocusPlanPage:
    return await _service(request, db, auth).list_focus_plans(
        limit=limit,
        cursor=cursor,
        work_item_id=work_item_id,
        template_only=template_only,
    )


@router.post(
    "/focus-plans",
    response_model=FocusPlan,
    status_code=status.HTTP_201_CREATED,
    operation_id="createFocusPlan",
)
async def create_focus_plan(
    payload: CreateFocusPlanRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    idempotency_key: IdempotencyKey,
) -> FocusPlan:
    plan = await _service(request, db, auth).create_focus_plan(payload, idempotency_key)
    _focus_plan_etag(response, plan)
    response.headers["Location"] = f"{request.app.state.settings.api_prefix}/focus-plans/{plan.id}"
    return plan


@router.get(
    "/focus-plans/{focusPlanId}",
    response_model=FocusPlan,
    operation_id="getFocusPlan",
)
async def get_focus_plan(
    focus_plan_id: FocusPlanId,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> FocusPlan:
    plan = await _service(request, db, auth).get_focus_plan(focus_plan_id)
    _focus_plan_etag(response, plan)
    return plan


@router.patch(
    "/focus-plans/{focusPlanId}",
    response_model=FocusPlan,
    operation_id="updateFocusPlan",
)
async def update_focus_plan(
    focus_plan_id: FocusPlanId,
    payload: UpdateFocusPlanRequest,
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> FocusPlan:
    plan = await _service(request, db, auth).update_focus_plan(focus_plan_id, payload, if_match)
    _focus_plan_etag(response, plan)
    return plan


@router.delete(
    "/focus-plans/{focusPlanId}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteFocusPlan",
)
async def delete_focus_plan(
    focus_plan_id: FocusPlanId,
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
    if_match: IfMatch = None,
) -> Response:
    await _service(request, db, auth).delete_focus_plan(focus_plan_id, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
