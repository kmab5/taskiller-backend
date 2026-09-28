from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from taskiller.api.models import ApiModel


class FocusSegmentKind(StrEnum):
    WORK = "work"
    BREAK = "break"
    LONG_BREAK = "long_break"
    RETRIEVAL = "retrieval"
    REVIEW = "review"
    PLANNING = "planning"
    TRANSITION = "transition"


class DurationMode(StrEnum):
    FIXED = "fixed"
    FLEXIBLE = "flexible"
    OPEN = "open"


class FocusPlanSource(StrEnum):
    MANUAL = "manual"
    RECOMMENDATION = "recommendation"
    TEMPLATE = "template"


class RecommendationStrategy(StrEnum):
    AUTO = "auto"
    CONTINUOUS = "continuous"
    STRUCTURED = "structured"
    FLEXIBLE = "flexible"


class RecommendationProvenance(StrEnum):
    BOOTSTRAP = "bootstrap"
    PREFERENCE_INFORMED = "preference_informed"
    HISTORY_INFORMED = "history_informed"


class RecommendationReasonLabel(StrEnum):
    EVIDENCE_BACKED_GENERAL = "evidence_backed_general"
    EVIDENCE_MIXED = "evidence_mixed"
    PRODUCT_HEURISTIC = "product_heuristic"
    PERSONAL_PATTERN = "personal_pattern"
    USER_PREFERENCE = "user_preference"


class FocusPlanSegmentInput(ApiModel):
    kind: FocusSegmentKind
    duration_mode: DurationMode
    target_seconds: int | None = Field(default=None, ge=1, le=86_400)
    min_seconds: int | None = Field(default=None, ge=0, le=86_400)
    max_seconds: int | None = Field(default=None, ge=1, le=86_400)
    linked_work_item_id: UUID | None = None
    optional: bool = False
    label: str | None = Field(default=None, max_length=300)
    instructions: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_duration_shape(self) -> Self:
        if self.duration_mode in {DurationMode.FIXED, DurationMode.FLEXIBLE}:
            if self.target_seconds is None:
                raise ValueError("fixed and flexible segments require targetSeconds")
        if (
            self.min_seconds is not None
            and self.max_seconds is not None
            and self.min_seconds > self.max_seconds
        ):
            raise ValueError("minSeconds cannot exceed maxSeconds")
        if (
            self.target_seconds is not None
            and self.min_seconds is not None
            and self.target_seconds < self.min_seconds
        ):
            raise ValueError("targetSeconds cannot be below minSeconds")
        if (
            self.target_seconds is not None
            and self.max_seconds is not None
            and self.target_seconds > self.max_seconds
        ):
            raise ValueError("targetSeconds cannot exceed maxSeconds")
        if self.kind in {
            FocusSegmentKind.BREAK,
            FocusSegmentKind.LONG_BREAK,
            FocusSegmentKind.TRANSITION,
        } and self.linked_work_item_id is not None:
            raise ValueError("break and transition segments cannot link a work item")
        return self


class FocusPlanSegment(FocusPlanSegmentInput):
    id: UUID
    index: int = Field(ge=0)


class FocusPlanSnapshot(ApiModel):
    strategy: str | None = None
    segments: list[FocusPlanSegmentInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_executable_segment(self) -> Self:
        if not any(
            segment.kind
            not in {
                FocusSegmentKind.BREAK,
                FocusSegmentKind.LONG_BREAK,
                FocusSegmentKind.TRANSITION,
            }
            for segment in self.segments
        ):
            raise ValueError("a focus plan must contain at least one executable segment")
        return self


class RecommendationReason(ApiModel):
    code: str
    label: RecommendationReasonLabel
    message: str


class CreateRecommendationRequest(ApiModel):
    work_item_id: UUID
    available_time_seconds: int | None = Field(default=None, ge=300, le=43_200)
    preferred_strategy: RecommendationStrategy = RecommendationStrategy.AUTO


class FocusPlanRecommendation(ApiModel):
    id: UUID
    work_item_id: UUID
    engine_version: str
    provenance: RecommendationProvenance
    plan: FocusPlanSnapshot
    reasons: list[RecommendationReason]
    created_at: datetime


class CreateFocusPlanRequest(ApiModel):
    work_item_id: UUID | None = None
    recommendation_id: UUID | None = None
    source: FocusPlanSource
    name: str = Field(min_length=1, max_length=200)
    template: bool = False
    segments: list[FocusPlanSegmentInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_source_shape(self) -> Self:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        if self.source is FocusPlanSource.RECOMMENDATION and self.recommendation_id is None:
            raise ValueError("recommendation source requires recommendationId")
        if self.source is not FocusPlanSource.RECOMMENDATION and self.recommendation_id is not None:
            raise ValueError("recommendationId is only valid for recommendation source")
        if self.source is FocusPlanSource.TEMPLATE and not self.template:
            raise ValueError("template source requires template=true")
        if self.template and self.source is not FocusPlanSource.TEMPLATE:
            raise ValueError("template=true requires source=template")
        if self.template and self.work_item_id is not None:
            raise ValueError("templates cannot be bound to a work item")
        if self.template and any(s.linked_work_item_id is not None for s in self.segments):
            raise ValueError("template segments cannot link work items")
        FocusPlanSnapshot(segments=self.segments)
        return self


class UpdateFocusPlanRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    template: bool | None = None
    segments: list[FocusPlanSegmentInput] | None = Field(
        default=None, min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if "name" in self.model_fields_set:
            if self.name is None:
                raise ValueError("name cannot be null")
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name must not be blank")
        if "template" in self.model_fields_set and self.template is None:
            raise ValueError("template cannot be null")
        if "segments" in self.model_fields_set:
            if self.segments is None:
                raise ValueError("segments cannot be null")
            FocusPlanSnapshot(segments=self.segments)
        return self


class FocusPlan(ApiModel):
    id: UUID
    work_item_id: UUID | None
    recommendation_id: UUID | None
    source: FocusPlanSource
    name: str
    template: bool
    segments: list[FocusPlanSegment]
    created_at: datetime
    updated_at: datetime
    version: int


class PageMeta(ApiModel):
    has_more: bool
    next_cursor: str | None


class FocusPlanPage(ApiModel):
    items: list[FocusPlan]
    page: PageMeta
