from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from asgiref.sync import async_to_sync
from django.db import IntegrityError, transaction

from taskiller.auth.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    normalize_email,
    password_hasher,
)
from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.runtime import auth_email_sender, taskiller_settings
from taskiller.django_domain.models import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    TaskillerUser,
    UserPreferences,
)

logger = logging.getLogger(__name__)
_DUMMY_PASSWORD_HASH = password_hasher.hash("taskiller-dummy-password-not-a-user")


@dataclass(slots=True)
class IssuedCredentials:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: TaskillerUser
    auth_session: AuthSession


class DjangoAuthService:
    def __init__(self) -> None:
        self.settings = taskiller_settings()

    def register(
        self,
        payload: dict[str, object],
        device_name: str | None,
    ) -> IssuedCredentials:
        email = normalize_email(str(payload["email"]))
        timezone = str(payload.get("timezone") or "UTC")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise TaskillerAPIError(
                422,
                "invalid_timezone",
                "Invalid timezone",
                "timezone must be a valid IANA timezone name.",
            ) from exc

        now = utc_now()
        user_id = uuid4()
        session, refresh_plain, refresh_row = self._build_auth_session(
            user_id,
            device_name,
            now,
        )

        try:
            with transaction.atomic():
                user = TaskillerUser.objects.create(
                    id=user_id,
                    email=email,
                    password_hash=password_hasher.hash(str(payload["password"])),
                    display_name=payload.get("display_name"),
                    email_verified_at=None,
                    password_changed_at=now,
                    is_active=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                UserPreferences.objects.create(
                    user_id=user.id,
                    timezone=timezone,
                    locale=str(payload.get("locale") or "en"),
                    week_starts_on=1,
                    preferred_strategy="auto",
                    preferred_work_block_min_seconds=None,
                    preferred_work_block_max_seconds=None,
                    show_review_prompt=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.save(force_insert=True)
                refresh_row.save(force_insert=True)
        except IntegrityError as exc:
            raise TaskillerAPIError(
                409,
                "email_already_registered",
                "Email already registered",
                "An account already exists for this email address.",
            ) from exc

        return self._issue(user, session, refresh_plain)

    def login(self, payload: dict[str, object]) -> IssuedCredentials:
        email = normalize_email(str(payload["email"]))

        with transaction.atomic():
            user = TaskillerUser.objects.select_for_update().filter(email=email).first()
            if user is None:
                password_hasher.verify(str(payload["password"]), _DUMMY_PASSWORD_HASH)
                raise self._invalid_credentials()
            if not user.is_active or not password_hasher.verify(
                str(payload["password"]),
                user.password_hash,
            ):
                raise self._invalid_credentials()

            now = utc_now()
            session, refresh_plain, refresh_row = self._build_auth_session(
                user.id,
                payload.get("device_name"),
                now,
            )
            session.save(force_insert=True)
            refresh_row.save(force_insert=True)

        return self._issue(user, session, refresh_plain)

    def refresh(self, presented_refresh: str) -> IssuedCredentials:
        token_hash = hash_opaque_token(presented_refresh, self.settings)
        first = RefreshToken.objects.filter(token_hash=token_hash).first()
        if first is None:
            raise self._invalid_refresh()

        deferred_error: TaskillerAPIError | None = None
        issued: IssuedCredentials | None = None

        with transaction.atomic():
            session = AuthSession.objects.select_for_update().filter(id=first.session_id).first()
            if session is None:
                deferred_error = self._invalid_refresh()
            else:
                current = RefreshToken.objects.select_for_update().filter(id=first.id).first()
                if current is None:
                    deferred_error = self._invalid_refresh()
                else:
                    now = utc_now()
                    if current.rotated_at is not None:
                        self._revoke_locked_session(
                            session,
                            now,
                            "refresh_token_reuse",
                        )
                        deferred_error = TaskillerAPIError(
                            401,
                            "refresh_token_reuse",
                            "Refresh token reuse detected",
                            "The device session was revoked because an old refresh token was replayed.",
                        )
                    elif current.revoked_at is not None:
                        deferred_error = self._invalid_refresh()
                    elif current.expires_at <= now or session.expires_at <= now:
                        self._revoke_locked_session(session, now, "expired")
                        deferred_error = self._invalid_refresh()
                    elif session.revoked_at is not None:
                        deferred_error = self._invalid_refresh()
                    else:
                        user = TaskillerUser.objects.filter(id=session.user_id).first()
                        if user is None or not user.is_active:
                            self._revoke_locked_session(
                                session,
                                now,
                                "user_inactive",
                            )
                            deferred_error = self._invalid_refresh()
                        else:
                            replacement_plain = generate_opaque_token()
                            replacement = RefreshToken.objects.create(
                                id=uuid4(),
                                session_id=session.id,
                                token_hash=hash_opaque_token(
                                    replacement_plain,
                                    self.settings,
                                ),
                                created_at=now,
                                expires_at=session.expires_at,
                                rotated_at=None,
                                revoked_at=None,
                                replaced_by_id=None,
                            )
                            current.rotated_at = now
                            current.replaced_by_id = replacement.id
                            current.save(update_fields=["rotated_at", "replaced_by"])
                            session.last_used_at = now
                            session.save(update_fields=["last_used_at"])
                            issued = self._issue(
                                user,
                                session,
                                replacement_plain,
                            )

        if deferred_error is not None:
            raise deferred_error
        if issued is None:
            raise self._invalid_refresh()
        return issued

    def revoke_session(self, user_id: UUID, session_id: UUID, reason: str) -> bool:
        with transaction.atomic():
            session = (
                AuthSession.objects.select_for_update()
                .filter(id=session_id, user_id=user_id)
                .first()
            )
            if session is None:
                return False
            if session.revoked_at is None:
                self._revoke_locked_session(session, utc_now(), reason)
        return True

    def revoke_all_sessions(self, user_id: UUID, reason: str) -> None:
        now = utc_now()
        with transaction.atomic():
            sessions = list(
                AuthSession.objects.select_for_update()
                .filter(user_id=user_id, revoked_at__isnull=True)
                .order_by("id")
            )
            for session in sessions:
                self._revoke_locked_session(session, now, reason)

    def request_email_verification(self, user: TaskillerUser) -> None:
        with transaction.atomic():
            locked = TaskillerUser.objects.select_for_update().get(id=user.id)
            if locked.email_verified_at is not None or not locked.is_active:
                return
            now = utc_now()
            EmailVerificationToken.objects.filter(
                user_id=locked.id,
                consumed_at__isnull=True,
            ).update(consumed_at=now)
            plain = generate_opaque_token()
            EmailVerificationToken.objects.create(
                id=uuid4(),
                user_id=locked.id,
                token_hash=hash_opaque_token(plain, self.settings),
                created_at=now,
                expires_at=now + timedelta(minutes=self.settings.email_verification_ttl_minutes),
                consumed_at=None,
            )
            email = locked.email

        try:
            async_to_sync(auth_email_sender().send_email_verification)(email, plain)
        except Exception as exc:
            logger.exception(
                "email_verification_delivery_failed",
                extra={"user_id": str(user.id)},
            )
            raise TaskillerAPIError(
                503,
                "email_delivery_unavailable",
                "Email delivery unavailable",
                "Taskiller could not reach the configured email provider. Try again later.",
            ) from exc

    def confirm_email_verification(self, token: str) -> None:
        now = utc_now()
        token_hash = hash_opaque_token(token, self.settings)
        first = EmailVerificationToken.objects.filter(token_hash=token_hash).first()
        if first is None:
            raise self._invalid_one_time_token("email_verification_token_invalid")

        with transaction.atomic():
            user = TaskillerUser.objects.select_for_update().filter(id=first.user_id).first()
            row = EmailVerificationToken.objects.select_for_update().filter(id=first.id).first()
            if (
                user is None
                or row is None
                or row.consumed_at is not None
                or row.expires_at <= now
                or not user.is_active
            ):
                raise self._invalid_one_time_token("email_verification_token_invalid")
            row.consumed_at = now
            row.save(update_fields=["consumed_at"])
            if user.email_verified_at is None:
                user.email_verified_at = now
                user.updated_at = now
                user.version += 1
                user.save(
                    update_fields=[
                        "email_verified_at",
                        "updated_at",
                        "version",
                    ]
                )

    def request_password_reset(self, email_value: str) -> None:
        email = normalize_email(email_value)

        with transaction.atomic():
            user = TaskillerUser.objects.select_for_update().filter(email=email).first()
            if user is None or not user.is_active:
                return
            now = utc_now()
            PasswordResetToken.objects.filter(
                user_id=user.id,
                consumed_at__isnull=True,
            ).update(consumed_at=now)
            plain = generate_opaque_token()
            PasswordResetToken.objects.create(
                id=uuid4(),
                user_id=user.id,
                token_hash=hash_opaque_token(plain, self.settings),
                created_at=now,
                expires_at=now + timedelta(minutes=self.settings.password_reset_ttl_minutes),
                consumed_at=None,
            )
            recipient = user.email
            user_id = user.id

        try:
            async_to_sync(auth_email_sender().send_password_reset)(recipient, plain)
        except Exception as exc:
            logger.exception(
                "password_reset_delivery_failed",
                extra={"user_id": str(user_id)},
            )
            raise TaskillerAPIError(
                503,
                "email_delivery_unavailable",
                "Email delivery unavailable",
                "Taskiller could not reach the configured email provider. Try again later.",
            ) from exc

    def confirm_password_reset(self, token: str, new_password: str) -> None:
        new_hash = password_hasher.hash(new_password)
        token_hash = hash_opaque_token(token, self.settings)
        first = PasswordResetToken.objects.filter(token_hash=token_hash).first()
        if first is None:
            raise self._invalid_one_time_token("password_reset_token_invalid")

        with transaction.atomic():
            user = TaskillerUser.objects.select_for_update().filter(id=first.user_id).first()
            row = PasswordResetToken.objects.select_for_update().filter(id=first.id).first()
            now = utc_now()
            if (
                user is None
                or row is None
                or row.consumed_at is not None
                or row.expires_at <= now
                or not user.is_active
            ):
                raise self._invalid_one_time_token("password_reset_token_invalid")

            user.password_hash = new_hash
            user.password_changed_at = now
            user.updated_at = now
            user.version += 1
            user.save(
                update_fields=[
                    "password_hash",
                    "password_changed_at",
                    "updated_at",
                    "version",
                ]
            )
            PasswordResetToken.objects.filter(
                user_id=user.id,
                consumed_at__isnull=True,
            ).update(consumed_at=now)
            sessions = list(
                AuthSession.objects.select_for_update()
                .filter(user_id=user.id, revoked_at__isnull=True)
                .order_by("id")
            )
            for session in sessions:
                self._revoke_locked_session(session, now, "password_reset")

    def _revoke_locked_session(
        self,
        session: AuthSession,
        now: datetime,
        reason: str,
    ) -> None:
        session.revoked_at = now
        session.revocation_reason = reason
        session.save(update_fields=["revoked_at", "revocation_reason"])
        RefreshToken.objects.filter(
            session_id=session.id,
            revoked_at__isnull=True,
        ).update(revoked_at=now)

    def _build_auth_session(
        self,
        user_id: UUID,
        device_name: object,
        now: datetime,
    ) -> tuple[AuthSession, str, RefreshToken]:
        expires_at = now + timedelta(days=self.settings.refresh_token_ttl_days)
        session = AuthSession(
            id=uuid4(),
            user_id=user_id,
            device_name=(str(device_name).strip()[:200] if device_name else None),
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
            revoked_at=None,
            revocation_reason=None,
        )
        refresh_plain = generate_opaque_token()
        refresh = RefreshToken(
            id=uuid4(),
            session_id=session.id,
            token_hash=hash_opaque_token(refresh_plain, self.settings),
            created_at=now,
            expires_at=expires_at,
            rotated_at=None,
            revoked_at=None,
            replaced_by_id=None,
        )
        return session, refresh_plain, refresh

    def _issue(
        self,
        user: TaskillerUser,
        session: AuthSession,
        refresh_token: str,
    ) -> IssuedCredentials:
        access, access_expires = create_access_token(
            user.id,
            session.id,
            self.settings,
        )
        return IssuedCredentials(
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=refresh_token,
            refresh_expires_at=session.expires_at,
            user=user,
            auth_session=session,
        )

    @staticmethod
    def _invalid_credentials() -> TaskillerAPIError:
        return TaskillerAPIError(
            401,
            "invalid_credentials",
            "Invalid credentials",
            "The email address or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _invalid_refresh() -> TaskillerAPIError:
        return TaskillerAPIError(
            401,
            "invalid_refresh_token",
            "Invalid refresh token",
            "The refresh credential is invalid, expired, or revoked.",
        )

    @staticmethod
    def _invalid_one_time_token(code: str) -> TaskillerAPIError:
        return TaskillerAPIError(
            400,
            code,
            "Invalid or expired token",
            "The one-time token is invalid, expired, or has already been used.",
        )
