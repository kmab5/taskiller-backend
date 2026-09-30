from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from taskiller.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("version >= 1", name="ck_users_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    preferences: Mapped[UserPreferences] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    auth_sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserPreferences(TimestampMixin, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("week_starts_on BETWEEN 0 AND 6", name="ck_preferences_week_starts_on"),
        CheckConstraint("version >= 1", name="ck_preferences_version_positive"),
        CheckConstraint(
            "preferred_strategy IN ('auto', 'continuous', 'structured', 'flexible')",
            name="ck_preferences_strategy",
        ),
        CheckConstraint(
            "preferred_work_block_min_seconds IS NULL OR preferred_work_block_min_seconds >= 60",
            name="ck_preferences_min_block",
        ),
        CheckConstraint(
            "preferred_work_block_max_seconds IS NULL OR preferred_work_block_max_seconds >= 60",
            name="ck_preferences_max_block",
        ),
        CheckConstraint(
            "preferred_work_block_min_seconds IS NULL OR "
            "preferred_work_block_max_seconds IS NULL OR "
            "preferred_work_block_min_seconds <= preferred_work_block_max_seconds",
            name="ck_preferences_block_range",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    locale: Mapped[str] = mapped_column(String(40), nullable=False, default="en")
    week_starts_on: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    preferred_strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    preferred_work_block_min_seconds: Mapped[int | None] = mapped_column(Integer)
    preferred_work_block_max_seconds: Mapped[int | None] = mapped_column(Integer)
    show_review_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user: Mapped[User] = relationship(back_populates="preferences")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_active", "user_id", "revoked_at", "expires_at"),
        CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(80))

    user: Mapped[User] = relationship(back_populates="auth_sessions")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="RefreshToken.session_id",
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        Index("ix_refresh_tokens_session", "session_id", "created_at"),
        CheckConstraint("expires_at > created_at", name="ck_refresh_tokens_expiry"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )

    session: Mapped[AuthSession] = relationship(
        back_populates="refresh_tokens", foreign_keys=[session_id]
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_email_verification_hash"),
        CheckConstraint("expires_at > created_at", name="ck_email_verification_expiry"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_hash"),
        CheckConstraint("expires_at > created_at", name="ck_password_reset_expiry"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (Index("ix_idempotency_records_expiry", "expires_at"),)

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(160), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    resource_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
