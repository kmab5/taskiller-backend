from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class EmailDeliveryMode(StrEnum):
    DEVELOPMENT_LOG = "development_log"
    SAFE_LOG = "safe_log"
    SMTP = "smtp"
    MAILJET = "mailjet"


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
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    trust_forwarded_for: bool = False
    security_headers_enabled: bool = True
    hsts_max_age_seconds: int = Field(default=31_536_000, ge=0, le=63_072_000)
    embedded_worker_enabled: bool = False

    database_url: str = "postgresql+psycopg://taskiller:taskiller@localhost:5432/taskiller"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3600)

    email_delivery_mode: EmailDeliveryMode = EmailDeliveryMode.DEVELOPMENT_LOG
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

    web_app_url: str = "http://localhost:5173"
    mailjet_api_key: str | None = None
    mailjet_secret_key: str | None = None
    mailjet_from_email: str | None = None
    mailjet_from_name: str = "Taskiller"
    mailjet_api_url: str = "https://api.mailjet.com/v3.1/send"
    mailjet_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

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
    def is_deployed(self) -> bool:
        return self.env in {Environment.STAGING, Environment.PRODUCTION}

    @property
    def cookie_secure(self) -> bool:
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.is_deployed

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if self.refresh_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("refresh_cookie_samesite must be lax, strict, or none")
        if self.refresh_cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None refresh cookies must be Secure")
        if not self.api_prefix.startswith("/") or self.api_prefix.endswith("/"):
            raise ValueError("api_prefix must start with '/' and must not end with '/'")
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must contain at least one host")
        if self.is_deployed:
            if self.jwt_secret.startswith("change-me-") or len(self.jwt_secret) < 32:
                raise ValueError("A strong TASKILLER_JWT_SECRET is required outside local/test")
            if self.token_hash_secret.startswith("change-me-") or len(self.token_hash_secret) < 32:
                raise ValueError(
                    "A strong TASKILLER_TOKEN_HASH_SECRET is required outside local/test"
                )
            if self.env is Environment.PRODUCTION:
                if self.email_delivery_mode is EmailDeliveryMode.SMTP:
                    if not self.smtp_host or not self.smtp_from_email:
                        raise ValueError("Production SMTP requires host and from email")
                    if bool(self.smtp_username) != bool(self.smtp_password):
                        raise ValueError("SMTP username and password must be configured together")
                elif self.email_delivery_mode is EmailDeliveryMode.MAILJET:
                    if (
                        not self.mailjet_api_key
                        or not self.mailjet_secret_key
                        or not self.mailjet_from_email
                    ):
                        raise ValueError(
                            "Production Mailjet requires API key, secret key, and from email"
                        )
                    mailjet_url = urlparse(self.mailjet_api_url)
                    if mailjet_url.scheme != "https" or not mailjet_url.netloc:
                        raise ValueError("TASKILLER_MAILJET_API_URL must be an absolute HTTPS URL")
                else:
                    raise ValueError(
                        "Production requires TASKILLER_EMAIL_DELIVERY_MODE=smtp or mailjet"
                    )
                web_url = urlparse(self.web_app_url)
                if web_url.scheme not in {"http", "https"} or not web_url.netloc:
                    raise ValueError("TASKILLER_WEB_APP_URL must be an absolute HTTP(S) URL")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are forbidden outside local/test")
            if "*" in self.allowed_hosts:
                raise ValueError("Wildcard allowed_hosts are forbidden outside local/test")
            for origin in self.cors_origins:
                parsed = urlparse(origin)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError("Deployed CORS origins must be absolute HTTP(S) origins")
            lowered_url = self.database_url.casefold()
            if "localhost" in lowered_url or "127.0.0.1" in lowered_url:
                raise ValueError("A non-local TASKILLER_DATABASE_URL is required when deployed")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
