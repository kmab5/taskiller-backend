from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from taskiller.api.models import ApiModel


def _normalize_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a UTC offset")
    return value.astimezone(UTC)


class IntensityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PhysicalityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    ACTIVE = "active"


class LearningMode(StrEnum):
    NONE = "none"
    ACQUISITION = "acquisition"
    RETRIEVAL = "retrieval"
    PRACTICE = "practice"


class WorkItemKind(StrEnum):
    PROJECT = "project"
    SPRINT = "sprint"
    CHORE = "chore"


class WorkItemStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class WorkCharacteristics(ApiModel):
    cognitive_demand: IntensityLevel
    interruption_sensitivity: IntensityLevel
    continuity_need: IntensityLevel
    repetitiveness: IntensityLevel
    physicality: PhysicalityLevel
    learning_mode: LearningMode


class PartialWorkCharacteristics(ApiModel):
    cognitive_demand: IntensityLevel | None = None
    interruption_sensitivity: IntensityLevel | None = None
    continuity_need: IntensityLevel | None = None
    repetitiveness: IntensityLevel | None = None
    physicality: PhysicalityLevel | None = None
    learning_mode: LearningMode | None = None

    def supplied_values(self) -> dict[str, str]:
        return {
            field: str(value)
            for field in self.model_fields_set
            if (value := getattr(self, field)) is not None
        }


class WorkTypeResponse(ApiModel):
    id: UUID
    slug: str
    display_name: str
    description: str | None
    characteristics: WorkCharacteristics
    system: bool
    version: int


class WorkTypeListResponse(ApiModel):
    items: list[WorkTypeResponse]


class CreateWorkTypeRequest(ApiModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    characteristics: WorkCharacteristics

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display name must not be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class UpdateWorkTypeRequest(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    characteristics: WorkCharacteristics | None = None

    @model_validator(mode="after")
    def reject_null_non_nullable_fields(self) -> Self:
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("displayName cannot be null")
        if "characteristics" in self.model_fields_set and self.characteristics is None:
            raise ValueError("characteristics cannot be null")
        return self

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display name must not be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class WorkItemResponse(ApiModel):
    id: UUID
    kind: WorkItemKind
    parent_id: UUID | None
    work_type_id: UUID | None
    name: str
    description: str | None
    status: WorkItemStatus
    position: int
    priority: int | None
    estimated_effort_seconds: int | None
    planned_start_at: datetime | None
    deadline_at: datetime | None
    target_start_date: date | None
    target_end_date: date | None
    characteristic_overrides: PartialWorkCharacteristics | None
    effective_characteristics: WorkCharacteristics | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int


class PageMeta(ApiModel):
    has_more: bool
    next_cursor: str | None


class WorkItemPage(ApiModel):
    items: list[WorkItemResponse]
    page: PageMeta


class WorkItemChildrenResponse(ApiModel):
    items: list[WorkItemResponse]


class WorkItemTreeNode(WorkItemResponse):
    children: list[WorkItemTreeNode]


class ProjectNextActionResponse(ApiModel):
    next_action: WorkItemResponse | None


class CreateWorkItemRequest(ApiModel):
    kind: WorkItemKind
    parent_id: UUID | None = None
    work_type_id: UUID | None = None
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    status: WorkItemStatus = WorkItemStatus.DRAFT
    priority: int | None = Field(default=None, ge=0, le=5)
    estimated_effort_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    planned_start_at: datetime | None = None
    deadline_at: datetime | None = None
    target_start_date: date | None = None
    target_end_date: date | None = None
    characteristic_overrides: PartialWorkCharacteristics | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("planned_start_at", "deadline_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _normalize_utc_datetime(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if (
            self.planned_start_at is not None
            and self.deadline_at is not None
            and self.planned_start_at > self.deadline_at
        ):
            raise ValueError("plannedStartAt cannot be after deadlineAt")
        if (
            self.target_start_date is not None
            and self.target_end_date is not None
            and self.target_start_date > self.target_end_date
        ):
            raise ValueError("targetStartDate cannot be after targetEndDate")
        return self


class UpdateWorkItemRequest(ApiModel):
    parent_id: UUID | None = None
    work_type_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    status: WorkItemStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=5)
    estimated_effort_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    planned_start_at: datetime | None = None
    deadline_at: datetime | None = None
    target_start_date: date | None = None
    target_end_date: date | None = None
    characteristic_overrides: PartialWorkCharacteristics | None = None

    @field_validator("planned_start_at", "deadline_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _normalize_utc_datetime(value)

    @model_validator(mode="after")
    def reject_null_non_nullable_fields(self) -> Self:
        for field in ("name", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ReorderWorkItemRequest(ApiModel):
    before_id: UUID | None = None
    after_id: UUID | None = None

    @model_validator(mode="after")
    def validate_anchor(self) -> Self:
        if self.before_id is not None and self.after_id is not None:
            raise ValueError("Supply at most one of beforeId or afterId")
        return self
