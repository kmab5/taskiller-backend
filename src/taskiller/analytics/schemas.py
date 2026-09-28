from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from taskiller.api.models import ApiModel


class AnalyticsBucket(StrEnum):
    DAY = "day"
    WEEK = "week"


class AnalyticsSummary(ApiModel):
    from_at: datetime = Field(alias="from")
    to_at: datetime = Field(alias="to")
    active_work_seconds: int = Field(ge=0)
    break_seconds: int = Field(ge=0)
    paused_seconds: int = Field(ge=0)
    sessions_completed: int = Field(ge=0)
    sessions_abandoned: int = Field(ge=0)
    chores_completed: int = Field(ge=0)
    median_uninterrupted_work_seconds: int | None = Field(default=None, ge=0)
    median_estimate_error_seconds: int | None = None
    median_start_delay_seconds: int | None = Field(default=None, ge=0)
    required_segments_completed: int = Field(ge=0)
    required_segments_planned: int = Field(ge=0)
    plan_adherence_rate: float | None = Field(default=None, ge=0, le=1)


class WorkTypeAnalytics(ApiModel):
    work_type_id: UUID | None
    work_type_slug: str | None
    active_work_seconds: int = Field(ge=0)
    session_count: int = Field(ge=0)
    median_uninterrupted_work_seconds: int | None = Field(default=None, ge=0)
    median_estimate_error_seconds: int | None = None
    completion_rate: float | None = Field(default=None, ge=0, le=1)
    median_focus_score: float | None = Field(default=None, ge=1, le=5)


class WorkTypeAnalyticsList(ApiModel):
    items: list[WorkTypeAnalytics]


class WorkItemAnalytics(ApiModel):
    work_item_id: UUID
    active_work_seconds: int = Field(ge=0)
    break_seconds: int = Field(ge=0)
    paused_seconds: int = Field(ge=0)
    session_count: int = Field(ge=0)
    estimate_error_seconds: int | None = None
    required_segments_completed: int = Field(ge=0)
    required_segments_planned: int = Field(ge=0)
    plan_adherence_rate: float | None = Field(default=None, ge=0, le=1)
    first_started_at: datetime | None
    completed_at: datetime | None


class AnalyticsTimeseriesPoint(ApiModel):
    bucket_start: datetime
    active_work_seconds: int = Field(ge=0)
    break_seconds: int = Field(ge=0)
    paused_seconds: int = Field(ge=0)
    sessions_completed: int = Field(ge=0)
    chores_completed: int = Field(ge=0)


class AnalyticsTimeseries(ApiModel):
    from_at: datetime = Field(alias="from")
    to_at: datetime = Field(alias="to")
    bucket: AnalyticsBucket
    timezone: str
    points: list[AnalyticsTimeseriesPoint]


class FocusPatternItem(ApiModel):
    work_type_id: UUID | None
    work_type_slug: str
    sample_size: int = Field(ge=0)
    median_uninterrupted_work_seconds: int | None = Field(default=None, ge=0)
    p25_uninterrupted_work_seconds: int | None = Field(default=None, ge=0)
    p75_uninterrupted_work_seconds: int | None = Field(default=None, ge=0)
    median_focus_score: float | None = Field(default=None, ge=1, le=5)
    recommendation_personalization_eligible: bool


class TimeOfDayPatternItem(ApiModel):
    hour_start: int = Field(ge=0, le=23)
    active_work_seconds: int = Field(ge=0)
    session_count: int = Field(ge=0)
    median_focus_score: float | None = Field(default=None, ge=1, le=5)


class FocusPatterns(ApiModel):
    from_at: datetime = Field(alias="from")
    to_at: datetime = Field(alias="to")
    timezone: str
    items: list[FocusPatternItem]
    time_of_day: list[TimeOfDayPatternItem]
