from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from taskiller.analytics.schemas import (
    AnalyticsBucket,
    AnalyticsSummary,
    AnalyticsTimeseries,
    FocusPatterns,
    WorkItemAnalytics,
    WorkTypeAnalyticsList,
)
from taskiller.analytics.service import AnalyticsService
from taskiller.auth.dependencies import CurrentAuth
from taskiller.db.dependencies import DbSession

router = APIRouter(prefix="/analytics", tags=["Analytics"])
WorkItemId = Annotated[UUID, Path(alias="workItemId")]
FromDateTime = Annotated[datetime, Query(alias="from")]
ToDateTime = Annotated[datetime, Query(alias="to")]


def _service(db: DbSession, auth: CurrentAuth) -> AnalyticsService:
    return AnalyticsService(db, owner_id=auth.user.id)


@router.get("/summary", response_model=AnalyticsSummary, operation_id="getAnalyticsSummary")
async def get_analytics_summary(
    db: DbSession,
    auth: CurrentAuth,
    from_at: FromDateTime,
    to_at: ToDateTime,
) -> AnalyticsSummary:
    return await _service(db, auth).summary(from_at, to_at)


@router.get(
    "/work-types",
    response_model=WorkTypeAnalyticsList,
    operation_id="getWorkTypeAnalytics",
)
async def get_work_type_analytics(
    db: DbSession,
    auth: CurrentAuth,
    from_at: FromDateTime,
    to_at: ToDateTime,
) -> WorkTypeAnalyticsList:
    return await _service(db, auth).work_types(from_at, to_at)


@router.get(
    "/work-items/{workItemId}",
    response_model=WorkItemAnalytics,
    operation_id="getWorkItemAnalytics",
)
async def get_work_item_analytics(
    work_item_id: WorkItemId,
    db: DbSession,
    auth: CurrentAuth,
    from_at: FromDateTime,
    to_at: ToDateTime,
) -> WorkItemAnalytics:
    return await _service(db, auth).work_item(work_item_id, from_at, to_at)


@router.get(
    "/timeseries",
    response_model=AnalyticsTimeseries,
    operation_id="getAnalyticsTimeseries",
)
async def get_analytics_timeseries(
    db: DbSession,
    auth: CurrentAuth,
    from_at: FromDateTime,
    to_at: ToDateTime,
    bucket: AnalyticsBucket,
) -> AnalyticsTimeseries:
    return await _service(db, auth).timeseries(from_at, to_at, bucket)


@router.get(
    "/focus-patterns",
    response_model=FocusPatterns,
    operation_id="getFocusPatterns",
)
async def get_focus_patterns(
    db: DbSession,
    auth: CurrentAuth,
    from_at: FromDateTime,
    to_at: ToDateTime,
) -> FocusPatterns:
    return await _service(db, auth).focus_patterns(from_at, to_at)
