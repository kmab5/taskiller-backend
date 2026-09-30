from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.auth.security import AccessClaims, decode_access_token
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.dependencies import get_db
from taskiller.db.models import AuthSession, User

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


@dataclass(slots=True)
class AuthContext:
    claims: AccessClaims
    user: User
    auth_session: AuthSession


async def get_current_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthContext:
    unauthorized = ApiError(
        401,
        "invalid_access_token",
        "Authentication required",
        "The access token is missing, invalid, expired, or belongs to a revoked session.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized

    claims = decode_access_token(credentials.credentials, request.app.state.settings)
    if claims is None:
        raise unauthorized

    stmt = (
        select(User, AuthSession)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            User.id == claims.user_id,
            AuthSession.id == claims.session_id,
            AuthSession.user_id == claims.user_id,
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise unauthorized
    user, auth_session = row
    now: datetime = utc_now()
    if not user.is_active or auth_session.revoked_at is not None or auth_session.expires_at <= now:
        raise unauthorized
    return AuthContext(claims=claims, user=user, auth_session=auth_session)


CurrentAuth = Annotated[AuthContext, Depends(get_current_auth)]
