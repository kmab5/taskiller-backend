from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from taskiller.api.models import ApiModel


class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str | None = Field(default=None, max_length=200)
    timezone: str = Field(default="UTC", max_length=100)
    locale: str = Field(default="en", max_length=40)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class LoginRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    device_name: str | None = Field(default=None, max_length=200)


class AuthSessionResponse(ApiModel):
    id: UUID
    device_name: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    current: bool


class AuthSessionsResponse(ApiModel):
    items: list[AuthSessionResponse]


class EmailVerificationConfirmRequest(ApiModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetRequest(ApiModel):
    email: EmailStr


class PasswordResetConfirmRequest(ApiModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=10, max_length=256)
