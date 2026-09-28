from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.auth.email import AuthEmailSender
from taskiller.auth.schemas import LoginRequest, RegisterRequest
from taskiller.auth.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    normalize_email,
    password_hasher,
)
from taskiller.core.config import Settings
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    User,
    UserPreferences,
)

_DUMMY_PASSWORD_HASH = password_hasher.hash("taskiller-dummy-password-not-a-user")


@dataclass(slots=True)
class IssuedCredentials:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: User
    auth_session: AuthSession


class AuthService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        email_sender: AuthEmailSender,
    ) -> None:
        self.db = db
        self.settings = settings
        self.email_sender = email_sender

    async def register(
        self, payload: RegisterRequest, device_name: str | None
    ) -> IssuedCredentials:
        email = normalize_email(str(payload.email))
        try:
            ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ApiError(
                422,
                "invalid_timezone",
                "Invalid timezone",
                "timezone must be a valid IANA timezone name.",
            ) from exc

        now = utc_now()
        user = User(
            id=uuid4(),
            email=email,
            password_hash=password_hasher.hash(payload.password),
            display_name=payload.display_name,
            email_verified_at=None,
            password_changed_at=now,
            is_active=True,
            version=1,
            created_at=now,
            updated_at=now,
        )
        preferences = UserPreferences(
            user_id=user.id,
            timezone=payload.timezone,
            locale=payload.locale,
            week_starts_on=1,
            preferred_strategy="auto",
            preferred_work_block_min_seconds=None,
            preferred_work_block_max_seconds=None,
            show_review_prompt=True,
            version=1,
            created_at=now,
            updated_at=now,
        )
        auth_session, refresh, refresh_row = self._build_auth_session(
            user.id, device_name, now
        )
        self.db.add_all([user, preferences, auth_session, refresh_row])
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ApiError(
                409,
                "email_already_registered",
                "Email already registered",
                "An account already exists for this email address.",
            ) from exc

        return self._issue(user, auth_session, refresh)

    async def login(self, payload: LoginRequest) -> IssuedCredentials:
        email = normalize_email(str(payload.email))
        stmt = select(User).where(User.email == email).with_for_update()
        user = (await self.db.execute(stmt)).scalar_one_or_none()
        if user is None:
            password_hasher.verify(payload.password, _DUMMY_PASSWORD_HASH)
            await self.db.rollback()
            raise self._invalid_credentials()
        if not user.is_active or not password_hasher.verify(payload.password, user.password_hash):
            await self.db.rollback()
            raise self._invalid_credentials()

        now = utc_now()
        auth_session, refresh, refresh_row = self._build_auth_session(
            user.id, payload.device_name, now
        )
        self.db.add_all([auth_session, refresh_row])
        await self.db.commit()
        return self._issue(user, auth_session, refresh)

    async def refresh(self, presented_refresh: str) -> IssuedCredentials:
        token_hash = hash_opaque_token(presented_refresh, self.settings)
        first = (
            await self.db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if first is None:
            await self.db.rollback()
            raise self._invalid_refresh()

        # Lock order for all refresh/revocation flows: session first, token second.
        auth_session = (
            await self.db.execute(
                select(AuthSession).where(AuthSession.id == first.session_id).with_for_update()
            )
        ).scalar_one_or_none()
        if auth_session is None:
            await self.db.rollback()
            raise self._invalid_refresh()
        current = (
            await self.db.execute(
                select(RefreshToken).where(RefreshToken.id == first.id).with_for_update()
            )
        ).scalar_one_or_none()
        if current is None:
            await self.db.rollback()
            raise self._invalid_refresh()

        now = utc_now()
        if current.rotated_at is not None:
            await self._revoke_locked_session(auth_session, now, "refresh_token_reuse")
            await self.db.commit()
            raise ApiError(
                401,
                "refresh_token_reuse",
                "Refresh token reuse detected",
                "The device session was revoked because an old refresh token was replayed.",
            )
        if current.revoked_at is not None:
            await self.db.rollback()
            raise self._invalid_refresh()
        if current.expires_at <= now or auth_session.expires_at <= now:
            await self._revoke_locked_session(auth_session, now, "expired")
            await self.db.commit()
            raise self._invalid_refresh()
        if auth_session.revoked_at is not None:
            await self.db.rollback()
            raise self._invalid_refresh()

        user = (
            await self.db.execute(select(User).where(User.id == auth_session.user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            await self._revoke_locked_session(auth_session, now, "user_inactive")
            await self.db.commit()
            raise self._invalid_refresh()

        replacement_plain = generate_opaque_token()
        replacement = RefreshToken(
            id=uuid4(),
            session_id=auth_session.id,
            token_hash=hash_opaque_token(replacement_plain, self.settings),
            created_at=now,
            expires_at=auth_session.expires_at,
            rotated_at=None,
            revoked_at=None,
            replaced_by_id=None,
        )
        current.rotated_at = now
        current.replaced_by_id = replacement.id
        auth_session.last_used_at = now
        self.db.add(replacement)
        await self.db.commit()
        return self._issue(user, auth_session, replacement_plain)

    async def revoke_session(self, user_id: UUID, session_id: UUID, reason: str) -> bool:
        auth_session = (
            await self.db.execute(
                select(AuthSession)
                .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if auth_session is None:
            await self.db.rollback()
            return False
        if auth_session.revoked_at is None:
            await self._revoke_locked_session(auth_session, utc_now(), reason)
        await self.db.commit()
        return True

    async def revoke_all_sessions(self, user_id: UUID, reason: str) -> None:
        now = utc_now()
        sessions = list(
            (
                await self.db.scalars(
                    select(AuthSession)
                    .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                    .order_by(AuthSession.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        for auth_session in sessions:
            await self._revoke_locked_session(auth_session, now, reason)
        await self.db.commit()

    async def request_email_verification(self, user: User) -> None:
        locked_user = (
            await self.db.execute(
                select(User)
                .where(User.id == user.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if locked_user.email_verified_at is not None or not locked_user.is_active:
            await self.db.rollback()
            return
        now = utc_now()
        await self.db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == locked_user.id,
                EmailVerificationToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        plain, row = self._build_email_verification(locked_user.id, now)
        self.db.add(row)
        await self.db.commit()
        await self.email_sender.send_email_verification(locked_user.email, plain)

    async def confirm_email_verification(self, token: str) -> None:
        now = utc_now()
        token_hash = hash_opaque_token(token, self.settings)
        first = (
            await self.db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.token_hash == token_hash
                )
            )
        ).scalar_one_or_none()
        if first is None:
            await self.db.rollback()
            raise self._invalid_one_time_token("email_verification_token_invalid")
        user = (
            await self.db.execute(select(User).where(User.id == first.user_id).with_for_update())
        ).scalar_one_or_none()
        row = (
            await self.db.execute(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.id == first.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            user is None
            or row is None
            or row.consumed_at is not None
            or row.expires_at <= now
            or not user.is_active
        ):
            await self.db.rollback()
            raise self._invalid_one_time_token("email_verification_token_invalid")
        row.consumed_at = now
        if user.email_verified_at is None:
            user.email_verified_at = now
            user.updated_at = now
            user.version += 1
        await self.db.commit()

    async def request_password_reset(self, email_value: str) -> None:
        email = normalize_email(email_value)
        user = (
            await self.db.execute(
                select(User).where(User.email == email).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            await self.db.rollback()
            return
        now = utc_now()
        await self.db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        plain = generate_opaque_token()
        row = PasswordResetToken(
            id=uuid4(),
            user_id=user.id,
            token_hash=hash_opaque_token(plain, self.settings),
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.password_reset_ttl_minutes),
            consumed_at=None,
        )
        self.db.add(row)
        await self.db.commit()
        await self.email_sender.send_password_reset(user.email, plain)

    async def confirm_password_reset(self, token: str, new_password: str) -> None:
        # Perform expensive Argon2 work before acquiring row locks.
        new_hash = password_hasher.hash(new_password)
        token_hash = hash_opaque_token(token, self.settings)
        first = (
            await self.db.execute(
                select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if first is None:
            await self.db.rollback()
            raise self._invalid_one_time_token("password_reset_token_invalid")

        # Login also locks the user row, preventing a stale-password session from being
        # committed concurrently with a password reset.
        user = (
            await self.db.execute(select(User).where(User.id == first.user_id).with_for_update())
        ).scalar_one_or_none()
        row = (
            await self.db.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.id == first.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = utc_now()
        if (
            user is None
            or row is None
            or row.consumed_at is not None
            or row.expires_at <= now
            or not user.is_active
        ):
            await self.db.rollback()
            raise self._invalid_one_time_token("password_reset_token_invalid")

        user.password_hash = new_hash
        user.password_changed_at = now
        user.updated_at = now
        user.version += 1
        await self.db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        sessions = list(
            (
                await self.db.scalars(
                    select(AuthSession)
                    .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                    .order_by(AuthSession.id)
                    .with_for_update()
                )
            ).all()
        )
        for auth_session in sessions:
            await self._revoke_locked_session(auth_session, now, "password_reset")
        await self.db.commit()

    async def _revoke_locked_session(
        self, auth_session: AuthSession, now: datetime, reason: str
    ) -> None:
        auth_session.revoked_at = now
        auth_session.revocation_reason = reason
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.session_id == auth_session.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    def _build_auth_session(
        self, user_id: UUID, device_name: str | None, now: datetime
    ) -> tuple[AuthSession, str, RefreshToken]:
        expires_at = now + timedelta(days=self.settings.refresh_token_ttl_days)
        auth_session = AuthSession(
            id=uuid4(),
            user_id=user_id,
            device_name=(device_name or None),
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
            revoked_at=None,
            revocation_reason=None,
        )
        refresh_plain = generate_opaque_token()
        refresh_row = RefreshToken(
            id=uuid4(),
            session_id=auth_session.id,
            token_hash=hash_opaque_token(refresh_plain, self.settings),
            created_at=now,
            expires_at=expires_at,
            rotated_at=None,
            revoked_at=None,
            replaced_by_id=None,
        )
        return auth_session, refresh_plain, refresh_row

    def _build_email_verification(
        self, user_id: UUID, now: datetime
    ) -> tuple[str, EmailVerificationToken]:
        plain = generate_opaque_token()
        return plain, EmailVerificationToken(
            id=uuid4(),
            user_id=user_id,
            token_hash=hash_opaque_token(plain, self.settings),
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.email_verification_ttl_minutes),
            consumed_at=None,
        )

    def _issue(
        self, user: User, auth_session: AuthSession, refresh_token: str
    ) -> IssuedCredentials:
        access, access_expires = create_access_token(
            user.id, auth_session.id, self.settings
        )
        return IssuedCredentials(
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=refresh_token,
            refresh_expires_at=auth_session.expires_at,
            user=user,
            auth_session=auth_session,
        )

    @staticmethod
    def _invalid_credentials() -> ApiError:
        return ApiError(
            401,
            "invalid_credentials",
            "Invalid credentials",
            "The email address or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _invalid_refresh() -> ApiError:
        return ApiError(
            401,
            "invalid_refresh_token",
            "Invalid refresh token",
            "The refresh credential is invalid, expired, or revoked.",
        )

    @staticmethod
    def _invalid_one_time_token(code: str) -> ApiError:
        return ApiError(
            400,
            code,
            "Invalid or expired token",
            "The one-time token is invalid, expired, or has already been used.",
        )
