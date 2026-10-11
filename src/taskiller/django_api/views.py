from __future__ import annotations

from datetime import UTC
from uuid import UUID

from django.db.models import F
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.core.time import utc_now
from taskiller.django_api.auth_service import DjangoAuthService, IssuedCredentials
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.privacy_service import (
    export_response,
    request_data_export,
    schedule_account_deletion,
    verify_export,
)
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_api.security import (
    enforce_rate_limit,
    record_security_event,
    request_subject,
)
from taskiller.django_api.serializers import (
    AccountDeletionResponseSerializer,
    AuthResponseSerializer,
    AuthSessionsResponseSerializer,
    DataExportResponseSerializer,
    EmailVerificationConfirmSerializer,
    LoginRequestSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterRequestSerializer,
    UpdatePreferencesSerializer,
    UpdateUserSerializer,
    UserPreferencesResponseSerializer,
    UserResponseSerializer,
)
from taskiller.django_api.user_service import (
    update_preferences,
    update_user,
)
from taskiller.django_domain.models import (
    AuthSession,
    DataExportRequest,
    UserPreferences,
)
from taskiller.users.etag import make_etag

REFRESH_COOKIE_NAME = "taskiller_refresh"


def _auth_service() -> DjangoAuthService:
    return DjangoAuthService()


def _auth_response(issued: IssuedCredentials) -> dict[str, object]:
    return {
        "accessToken": issued.access_token,
        "tokenType": "Bearer",
        "expiresIn": taskiller_settings().access_token_ttl_seconds,
        "user": UserResponseSerializer(issued.user).data,
    }


def _set_refresh_cookie(response: Response, issued: IssuedCredentials) -> None:
    settings = taskiller_settings()
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


def _clear_refresh_cookie(response: Response) -> None:
    settings = taskiller_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=f"{settings.api_prefix}/auth",
        domain=settings.refresh_cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


class RegisterView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="register",
        tags=["Auth"],
        request=RegisterRequestSerializer,
        responses={201: AuthResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = RegisterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = taskiller_settings()
        enforce_rate_limit(
            request,
            scope="auth_register",
            subject=request_subject(request, str(serializer.validated_data["email"])),
            limit=settings.auth_register_limit,
            window_seconds=settings.auth_register_window_seconds,
        )
        device_name = (request.headers.get("user-agent") or "")[:200] or None
        issued = _auth_service().register(serializer.validated_data, device_name)
        record_security_event(
            request,
            event_type="account_registered",
            user_id=issued.user.id,
        )
        response = Response(_auth_response(issued), status=201)
        _set_refresh_cookie(response, issued)
        return response


class LoginView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="login",
        tags=["Auth"],
        request=LoginRequestSerializer,
        responses={200: AuthResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = taskiller_settings()
        enforce_rate_limit(
            request,
            scope="auth_login",
            subject=request_subject(request, str(serializer.validated_data["email"])),
            limit=settings.auth_login_limit,
            window_seconds=settings.auth_login_window_seconds,
        )
        issued = _auth_service().login(serializer.validated_data)
        record_security_event(
            request,
            event_type="login_succeeded",
            user_id=issued.user.id,
        )
        response = Response(_auth_response(issued))
        _set_refresh_cookie(response, issued)
        return response


class RefreshView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="refreshAccessToken",
        tags=["Auth"],
        request=None,
        responses={200: AuthResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        refresh_token = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise TaskillerAPIError(
                401,
                "invalid_refresh_token",
                "Invalid refresh token",
                "The refresh credential is missing.",
            )
        issued = _auth_service().refresh(refresh_token)
        response = Response(_auth_response(issued))
        _set_refresh_cookie(response, issued)
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="logout", tags=["Auth"], request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        auth = request.auth
        _auth_service().revoke_session(
            auth.user.id,
            auth.auth_session.id,
            "logout",
        )
        response = Response(status=204)
        _clear_refresh_cookie(response)
        return response


class LogoutAllView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="logoutAll", tags=["Auth"], request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        _auth_service().revoke_all_sessions(request.auth.user.id, "logout_all")
        response = Response(status=204)
        _clear_refresh_cookie(response)
        return response


class SessionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="listAuthSessions",
        tags=["Auth"],
        responses={200: AuthSessionsResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        auth = request.auth
        now = utc_now()
        rows = AuthSession.objects.filter(
            user_id=auth.user.id,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).order_by(
            F("last_used_at").desc(nulls_last=True),
            F("created_at").desc(),
        )
        items = [
            {
                "id": row.id,
                "device_name": row.device_name,
                "created_at": row.created_at,
                "last_used_at": row.last_used_at,
                "expires_at": row.expires_at,
                "current": row.id == auth.auth_session.id,
            }
            for row in rows
        ]
        return Response(AuthSessionsResponseSerializer({"items": items}).data)


class SessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="revokeAuthSession",
        tags=["Auth"],
        responses={204: None},
    )
    def delete(self, request: Request, sessionId: UUID) -> Response:
        auth = request.auth
        found = _auth_service().revoke_session(
            auth.user.id,
            sessionId,
            "device_revoked",
        )
        if not found:
            raise TaskillerAPIError(
                404,
                "auth_session_not_found",
                "Session not found",
            )
        response = Response(status=204)
        if sessionId == auth.auth_session.id:
            _clear_refresh_cookie(response)
        return response


class RequestEmailVerificationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="requestEmailVerification",
        tags=["Auth"],
        request=None,
        responses={202: None},
    )
    def post(self, request: Request) -> Response:
        _auth_service().request_email_verification(request.auth.user)
        return Response(status=202)


class ConfirmEmailVerificationView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="confirmEmailVerification",
        tags=["Auth"],
        request=EmailVerificationConfirmSerializer,
        responses={204: None},
    )
    def post(self, request: Request) -> Response:
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth_service().confirm_email_verification(serializer.validated_data["token"])
        return Response(status=204)


class RequestPasswordResetView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="requestPasswordReset",
        tags=["Auth"],
        request=PasswordResetRequestSerializer,
        responses={202: None},
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = taskiller_settings()
        enforce_rate_limit(
            request,
            scope="password_reset",
            subject=request_subject(request, str(serializer.validated_data["email"])),
            limit=settings.auth_password_reset_limit,
            window_seconds=settings.auth_password_reset_window_seconds,
        )
        _auth_service().request_password_reset(str(serializer.validated_data["email"]))
        return Response(status=202)


class ConfirmPasswordResetView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="confirmPasswordReset",
        tags=["Auth"],
        request=PasswordResetConfirmSerializer,
        responses={204: None},
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth_service().confirm_password_reset(
            serializer.validated_data["token"],
            serializer.validated_data["new_password"],
        )
        return Response(status=204)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getMe",
        tags=["User"],
        responses={200: UserResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        user = request.auth.user
        response = Response(UserResponseSerializer(user).data)
        response["ETag"] = make_etag("user", user.id, user.version)
        return response

    @extend_schema(
        operation_id="updateMe",
        tags=["User"],
        request=UpdateUserSerializer,
        responses={200: UserResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = UpdateUserSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = update_user(
            request.auth.user.id,
            serializer.validated_data,
            request.headers.get("If-Match"),
        )
        response = Response(UserResponseSerializer(user).data)
        response["ETag"] = make_etag("user", user.id, user.version)
        return response

    @extend_schema(
        operation_id="requestAccountDeletion",
        tags=["User"],
        responses={202: AccountDeletionResponseSerializer},
    )
    def delete(self, request: Request) -> Response:
        user = request.auth.user
        enforce_rate_limit(
            request,
            scope="account_delete",
            subject=request_subject(request, str(user.id)),
            limit=2,
            window_seconds=3600,
        )
        deletion = schedule_account_deletion(
            user,
            request.headers.get("If-Match"),
        )
        record_security_event(
            request,
            event_type="account_deletion_scheduled",
            user_id=locked.id,
            metadata={"requestId": str(deletion.id)},
        )
        response = Response(
            {
                "requestId": deletion.id,
                "status": deletion.status,
                "requestedAt": deletion.requested_at,
                "executeAfter": deletion.execute_after,
            },
            status=202,
        )
        response["Clear-Site-Data"] = '"cookies", "storage"'
        return response


class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getPreferences",
        tags=["User"],
        responses={200: UserPreferencesResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        preferences = UserPreferences.objects.get(user_id=request.auth.user.id)
        response = Response(UserPreferencesResponseSerializer(preferences).data)
        response["ETag"] = make_etag(
            "preferences",
            request.auth.user.id,
            preferences.version,
        )
        return response

    @extend_schema(
        operation_id="updatePreferences",
        tags=["User"],
        request=UpdatePreferencesSerializer,
        responses={200: UserPreferencesResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = UpdatePreferencesSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        preferences = update_preferences(
            request.auth.user.id,
            serializer.validated_data,
            request.headers.get("If-Match"),
        )
        response = Response(UserPreferencesResponseSerializer(preferences).data)
        response["ETag"] = make_etag(
            "preferences",
            request.auth.user.id,
            preferences.version,
        )
        return response


class ExportRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="requestDataExport",
        tags=["User"],
        request=None,
        responses={202: DataExportResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        key = request.headers.get("Idempotency-Key", "")
        if not 8 <= len(key) <= 200:
            raise TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "One or more request values are invalid.",
            )
        settings = taskiller_settings()
        enforce_rate_limit(
            request,
            scope="data_export",
            subject=request_subject(request, str(request.auth.user.id)),
            limit=settings.export_request_limit,
            window_seconds=settings.export_request_window_seconds,
        )
        row = request_data_export(
            user_id=request.auth.user.id,
            idempotency_key=key,
        )
        record_security_event(
            request,
            event_type="data_export_requested",
            user_id=request.auth.user.id,
        )
        return Response(export_response(row), status=202)


class ExportRequestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="getDataExportRequest",
        tags=["User"],
        responses={200: DataExportResponseSerializer},
    )
    def get(self, request: Request, exportRequestId: UUID) -> Response:
        row = DataExportRequest.objects.filter(
            id=exportRequestId,
            user_id=request.auth.user.id,
        ).first()
        if row is None:
            raise TaskillerAPIError(
                404,
                "data_export_not_found",
                "Data export not found",
            )
        return Response(export_response(row))


class ExportDownloadView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="downloadDataExport",
        tags=["User"],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request: Request, exportRequestId: UUID) -> HttpResponse:
        token = request.query_params.get("token", "")
        if len(token) < 20:
            raise TaskillerAPIError(
                404,
                "data_export_not_found",
                "Data export not found",
            )
        row = DataExportRequest.objects.filter(id=exportRequestId).first()
        if not verify_export(row, export_id=exportRequestId, token=token):
            raise TaskillerAPIError(
                404,
                "data_export_not_found",
                "Data export not found",
            )
        assert row is not None and row.archive_bytes is not None
        response = HttpResponse(
            bytes(row.archive_bytes),
            content_type="application/gzip",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="taskiller-export-{exportRequestId}.json.gz"'
        )
        response["Cache-Control"] = "private, no-store"
        response["Digest"] = f"sha-256={row.archive_sha256}"
        return response
