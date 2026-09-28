from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TASKILLER_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Environment = Environment.LOCAL
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg://taskiller:taskiller@localhost:5432/taskiller"

    jwt_secret: str = "change-me-in-local-development"
    token_hash_secret: str = "change-me-in-local-development-token-hash"
    auth_issuer: str = "taskiller"
    auth_audience: str = "taskiller-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    email_verification_ttl_minutes: int = Field(default=60, ge=5, le=1440)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    idempotency_ttl_hours: int = Field(default=24, ge=1, le=168)

    account_deletion_grace_days: int = Field(default=7, ge=0, le=30)
    deletion_tombstone_retention_days: int = Field(default=30, ge=1, le=365)
    export_ttl_hours: int = Field(default=24, ge=1, le=168)
    export_download_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    export_request_limit: int = Field(default=3, ge=1, le=20)
    export_request_window_seconds: int = Field(default=3600, ge=60, le=86400)
    outbox_lease_seconds: int = Field(default=60, ge=10, le=3600)
    outbox_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    outbox_history_retention_days: int = Field(default=14, ge=1, le=365)
    security_event_retention_days: int = Field(default=90, ge=7, le=730)
    rate_limit_bucket_retention_seconds: int = Field(default=172800, ge=3600, le=604800)
    auth_login_limit: int = Field(default=10, ge=1, le=100)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86400)
    auth_register_limit: int = Field(default=5, ge=1, le=50)
    auth_register_window_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_password_reset_limit: int = Field(default=5, ge=1, le=50)
    auth_password_reset_window_seconds: int = Field(default=900, ge=60, le=86400)
    rate_limit_test_mode: bool = False

    refresh_cookie_domain: str | None = None
    refresh_cookie_samesite: str = "lax"
    refresh_cookie_secure: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def cookie_secure(self) -> bool:
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.env in {Environment.STAGING, Environment.PRODUCTION}

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if self.refresh_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("refresh_cookie_samesite must be lax, strict, or none")
        if self.refresh_cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None refresh cookies must be Secure")
        if self.env in {Environment.STAGING, Environment.PRODUCTION}:
            if self.jwt_secret.startswith("change-me-") or len(self.jwt_secret) < 32:
                raise ValueError("A strong TASKILLER_JWT_SECRET is required outside local/test")
            if self.token_hash_secret.startswith("change-me-") or len(self.token_hash_secret) < 32:
                raise ValueError(
                    "A strong TASKILLER_TOKEN_HASH_SECRET is required outside local/test"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
