from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware, _check_token_format
from django.utils.crypto import constant_time_compare
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_domain.models import StaffSession

from .permissions import effective_capabilities, require_capability

STAFF_COOKIE = "taskiller_staff"
CSRF_COOKIE = "taskiller_staff_csrf"
CHALLENGE_COOKIE = "taskiller_staff_challenge"
COOKIE_PATH = "/admin"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def auth_hash(enrollment):
    capabilities = ",".join(effective_capabilities(enrollment.user))
    return digest(f"{enrollment.user.get_session_auth_hash()}:{enrollment.version}:{capabilities}")


def set_cookie(response, name, value, max_age, httponly=True):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=COOKIE_PATH,
        secure=settings.ADMIN_CONSOLE_COOKIE_SECURE,
        httponly=httponly,
        samesite="Lax",
    )


def clear_cookie(response, name):
    set_cookie(response, name, "", 0)


class StaffCsrfMiddleware(CsrfViewMiddleware):
    def _get_secret(self, request):
        value = request.COOKIES.get(CSRF_COOKIE)
        if value is not None:
            _check_token_format(value)
        return value

    def _set_csrf_cookie(self, request, response):
        set_cookie(response, CSRF_COOKIE, request.META["CSRF_COOKIE"], 86400, httponly=False)


def check_csrf(request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("Origin") not in settings.ADMIN_CONSOLE_ORIGINS:
        raise TaskillerAPIError(403, "admin_origin_forbidden", "Unapproved staff console origin")
    raw = request._request
    middleware = StaffCsrfMiddleware(lambda r: None)
    middleware.process_request(raw)
    # APIView is csrf_exempt to Django's global middleware. Validate explicitly,
    # including anonymous password, invitation and MFA POSTs.
    rejection = middleware.process_view(raw, lambda r: None, (), {})
    if rejection is not None:
        raise TaskillerAPIError(403, "admin_csrf_failed", "Staff CSRF validation failed")


class StaffAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get(STAFF_COOKIE, "")
        if not token or len(token) > 200 or request.headers.get("Authorization"):
            raise TaskillerAPIError(401, "admin_auth_required", "Staff authentication required")
        row = (
            StaffSession.objects.select_related("enrollment__user")
            .filter(
                token_digest=digest(token),
                revoked_at__isnull=True,
            )
            .first()
        )
        now = utc_now()
        if row is None:
            raise TaskillerAPIError(401, "admin_auth_required", "Invalid staff session")
        enrollment = row.enrollment
        if (
            not enrollment.enabled
            or not enrollment.user.is_active
            or not enrollment.user.is_staff
            or not enrollment.mfa_secret_encrypted
            or row.expires_at <= now
            or row.last_seen_at <= now - timedelta(minutes=30)
            or not constant_time_compare(row.auth_hash, auth_hash(enrollment))
        ):
            StaffSession.objects.filter(id=row.id).update(revoked_at=now)
            raise TaskillerAPIError(401, "admin_auth_required", "Expired or revoked staff session")
        if row.last_seen_at < now - timedelta(minutes=1):
            StaffSession.objects.filter(id=row.id, last_seen_at=row.last_seen_at).update(
                last_seen_at=now
            )
            row.last_seen_at = now
        return enrollment.user, row

    def authenticate_header(self, request):
        return "StaffSession"


class StaffAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = StaffAuthentication
    name = "staffCookie"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": STAFF_COOKIE}


class AdminAPIView(APIView):
    authentication_classes = (StaffAuthentication,)
    permission_classes = (IsAuthenticated,)
    capability = None
    step_up = False
    writes = False

    def initial(self, request, *args, **kwargs):
        if not settings.ADMIN_CONSOLE_ENABLED:
            raise TaskillerAPIError(404, "admin_disabled", "Staff console is disabled")
        if self.writes and not settings.ADMIN_CONSOLE_WRITES_ENABLED:
            raise TaskillerAPIError(
                403, "admin_writes_disabled", "Staff console writes are disabled"
            )
        check_csrf(request)
        super().initial(request, *args, **kwargs)
        if self.authentication_classes:
            require_capability(request, self.capability, step_up=self.step_up)

    def handle_exception(self, exc):
        from .audit import record

        if isinstance(exc, TaskillerAPIError) and exc.status_code in {401, 403, 429}:
            record(
                self.request,
                "security.denied",
                outcome="denied",
                changes={"operation": self.__class__.__name__},
                reason=exc.code,
            )
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response


def new_session(enrollment):
    now = utc_now()
    token = secrets.token_urlsafe(48)
    row = StaffSession.objects.create(
        enrollment=enrollment,
        token_digest=digest(token),
        auth_hash=auth_hash(enrollment),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=8),
        mfa_verified_at=now,
    )
    return row, token
