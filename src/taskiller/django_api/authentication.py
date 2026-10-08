from __future__ import annotations

from dataclasses import dataclass

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from taskiller.auth.security import AccessClaims, decode_access_token
from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import AuthSession, TaskillerUser


@dataclass(slots=True)
class AuthContext:
    claims: AccessClaims
    user: TaskillerUser
    auth_session: AuthSession


def _unauthorized() -> TaskillerAPIError:
    return TaskillerAPIError(
        401,
        "invalid_access_token",
        "Authentication required",
        "The access token is missing, invalid, expired, or belongs to a revoked session.",
        headers={"WWW-Authenticate": "Bearer"},
    )


class TaskillerBearerAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[TaskillerUser, AuthContext] | None:
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        parts = header.split(None, 1)
        if len(parts) != 2 or parts[0].casefold() != "bearer":
            raise _unauthorized()

        claims = decode_access_token(parts[1], taskiller_settings())
        if claims is None:
            raise _unauthorized()

        session = (
            AuthSession.objects.select_related("user")
            .filter(
                id=claims.session_id,
                user_id=claims.user_id,
            )
            .first()
        )
        if session is None:
            raise _unauthorized()

        now = utc_now()
        user = session.user
        if not user.is_active or session.revoked_at is not None or session.expires_at <= now:
            raise _unauthorized()

        context = AuthContext(
            claims=claims,
            user=user,
            auth_session=session,
        )
        return user, context

    def authenticate_header(self, request: Request) -> str:
        del request
        return "Bearer"
