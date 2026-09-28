from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, Path as ApiPath, Request, Response, status
from sqlalchemy import select

from taskiller.auth.dependencies import CurrentAuth
from taskiller.auth.schemas import (
    AuthSessionResponse,
    AuthSessionsResponse,
    EmailVerificationConfirmRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
)
from taskiller.auth.service import AuthService, IssuedCredentials
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.dependencies import DbSession
from taskiller.db.models import AuthSession
from taskiller.users.presenters import user_to_response
from taskiller.users.schemas import AuthResponse

router = APIRouter(prefix="/auth", tags=["Auth"])
REFRESH_COOKIE_NAME = "taskiller_refresh"
_SET_COOKIE_HEADERS = {
    "Set-Cookie": {
        "description": "Rotating HttpOnly Taskiller refresh credential.",
        "schema": {"type": "string"},
    }
}


def _service(request: Request, db: DbSession) -> AuthService:
    return AuthService(db, request.app.state.settings, request.app.state.auth_email_sender)


def _auth_response(issued: IssuedCredentials, request: Request) -> AuthResponse:
    return AuthResponse(
        access_token=issued.access_token,
        token_type="Bearer",
        expires_in=request.app.state.settings.access_token_ttl_seconds,
        user=user_to_response(issued.user),
    )


def _set_refresh_cookie(response: Response, request: Request, issued: IssuedCredentials) -> None:
    settings = request.app.state.settings
    now = utc_now()
    max_age = max(0, int((issued.refresh_expires_at - now).total_seconds()))
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=issued.refresh_token,
        max_age=max_age,
        expires=issued.refresh_expires_at.astimezone(UTC),
        path=f"{settings.api_prefix}/auth",
        domain=settings.refresh_cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=f"{settings.api_prefix}/auth",
        domain=settings.refresh_cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    responses={201: {"headers": _SET_COOKIE_HEADERS}},
    operation_id="register",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    issued = await _service(request, db).register(payload, (user_agent or "")[:200] or None)
    _set_refresh_cookie(response, request, issued)
    return _auth_response(issued, request)


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={200: {"headers": _SET_COOKIE_HEADERS}},
    operation_id="login",
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> AuthResponse:
    issued = await _service(request, db).login(payload)
    _set_refresh_cookie(response, request, issued)
    return _auth_response(issued, request)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    responses={200: {"headers": _SET_COOKIE_HEADERS}},
    operation_id="refreshAccessToken",
)
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> AuthResponse:
    if not refresh_token:
        raise ApiError(
            401,
            "invalid_refresh_token",
            "Invalid refresh token",
            "The refresh credential is missing.",
        )
    issued = await _service(request, db).refresh(refresh_token)
    _set_refresh_cookie(response, request, issued)
    return _auth_response(issued, request)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout"
)
async def logout(
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> None:
    await _service(request, db).revoke_session(auth.user.id, auth.auth_session.id, "logout")
    _clear_refresh_cookie(response, request)


@router.post(
    "/logout-all", status_code=status.HTTP_204_NO_CONTENT, operation_id="logoutAll"
)
async def logout_all(
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> None:
    await _service(request, db).revoke_all_sessions(auth.user.id, "logout_all")
    _clear_refresh_cookie(response, request)


@router.get(
    "/sessions", response_model=AuthSessionsResponse, operation_id="listAuthSessions"
)
async def list_sessions(db: DbSession, auth: CurrentAuth) -> AuthSessionsResponse:
    now = utc_now()
    rows = (
        await db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == auth.user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.last_used_at.desc().nullslast(), AuthSession.created_at.desc())
        )
    ).all()
    return AuthSessionsResponse(
        items=[
            AuthSessionResponse(
                id=row.id,
                device_name=row.device_name,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                current=row.id == auth.auth_session.id,
            )
            for row in rows
        ]
    )


@router.delete(
    "/sessions/{sessionId}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeAuthSession",
)
async def revoke_session(
    session_id: Annotated[UUID, ApiPath(alias="sessionId")],
    request: Request,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> None:
    found = await _service(request, db).revoke_session(auth.user.id, session_id, "device_revoked")
    if not found:
        raise ApiError(404, "auth_session_not_found", "Session not found")
    if session_id == auth.auth_session.id:
        _clear_refresh_cookie(response, request)


@router.post(
    "/email-verification/request",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestEmailVerification",
)
async def request_email_verification(
    request: Request,
    db: DbSession,
    auth: CurrentAuth,
) -> None:
    await _service(request, db).request_email_verification(auth.user)


@router.post(
    "/email-verification/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="confirmEmailVerification",
)
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    request: Request,
    db: DbSession,
) -> None:
    await _service(request, db).confirm_email_verification(payload.token)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestPasswordReset",
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: DbSession,
) -> None:
    await _service(request, db).request_password_reset(str(payload.email))


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="confirmPasswordReset",
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: DbSession,
) -> None:
    await _service(request, db).confirm_password_reset(payload.token, payload.new_password)
