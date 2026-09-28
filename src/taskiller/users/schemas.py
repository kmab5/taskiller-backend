from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from taskiller.api.models import ApiModel


class PreferredStrategy(StrEnum):
    AUTO = "auto"
    CONTINUOUS = "continuous"
    STRUCTURED = "structured"
    FLEXIBLE = "flexible"


class UserResponse(ApiModel):
    id: UUID
    email: str
    display_name: str | None
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    version: int


class AuthResponse(ApiModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    user: UserResponse


class UpdateUserRequest(ApiModel):
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UserPreferencesResponse(ApiModel):
    timezone: str
    locale: str
    week_starts_on: int
    preferred_strategy: PreferredStrategy
    preferred_work_block_min_seconds: int | None
    preferred_work_block_max_seconds: int | None
    show_review_prompt: bool
    version: int


class UpdatePreferencesRequest(ApiModel):
    timezone: str | None = Field(default=None, max_length=100)
    locale: str | None = Field(default=None, max_length=40)
    week_starts_on: int | None = Field(default=None, ge=0, le=6)
    preferred_strategy: PreferredStrategy | None = None
    preferred_work_block_min_seconds: int | None = Field(default=None, ge=60, le=21600)
    preferred_work_block_max_seconds: int | None = Field(default=None, ge=60, le=21600)
    show_review_prompt: bool | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("locale")
    @classmethod
    def clean_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("locale must not be blank")
        return value

    @model_validator(mode="after")
    def validate_block_range(self) -> UpdatePreferencesRequest:
        if (
            self.preferred_work_block_min_seconds is not None
            and self.preferred_work_block_max_seconds is not None
            and self.preferred_work_block_min_seconds > self.preferred_work_block_max_seconds
        ):
            raise ValueError("preferred minimum work block cannot exceed maximum")
        return self
