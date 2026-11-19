from __future__ import annotations

import secrets
from datetime import timedelta

import pyotp
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.middleware.csrf import get_token, rotate_token
from django.urls import path
from django.utils.crypto import constant_time_compare
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.security import enforce_rate_limit, request_subject
from taskiller.django_domain.models import (
    StaffChallenge,
    StaffEnrollment,
    StaffRecoveryCode,
    StaffSession,
)

from . import serializers as S
from .audit import record
from .authentication import (
    CHALLENGE_COOKIE,
    STAFF_COOKIE,
    AdminAPIView,
    StaffCsrfMiddleware,
    auth_hash,
    clear_cookie,
    digest,
    new_session,
    set_cookie,
)
from .permissions import GROUP_PREFIX, effective_capabilities, owner_lock


def cipher():
    if not settings.ADMIN_CONSOLE_ENCRYPTION_KEYS:
        raise TaskillerAPIError(
            503, "admin_encryption_unavailable", "Staff MFA encryption is not configured"
        )
    return MultiFernet([Fernet(key.encode()) for key in settings.ADMIN_CONSOLE_ENCRYPTION_KEYS])


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise TaskillerAPIError(
            401, "admin_mfa_invalid", "MFA enrollment requires operator recovery"
        ) from exc


def body(serializer, request):
    value = serializer(data=request.data)
    value.is_valid(raise_exception=True)
    return value.validated_data


def throttle(request, scope, subject=""):
    enforce_rate_limit(
        request,
        scope=f"staff:{scope}",
        subject=request_subject(request, subject),
        limit=5,
        window_seconds=300,
    )


def csrf_response(request, response, rotate=False):
    raw = request._request
    middleware = StaffCsrfMiddleware(lambda r: response)
    middleware.process_request(raw)
    if rotate:
        rotate_token(raw)
    token = get_token(raw)
    if isinstance(response.data, dict):
        response.data["csrfToken"] = token
    return middleware.process_response(raw, response)


def challenge(enrollment, purpose, payload=None):
    browser = secrets.token_urlsafe(48)
    row = StaffChallenge.objects.create(
        enrollment=enrollment,
        purpose=purpose,
        secret_digest=digest(browser),
        expires_at=utc_now() + timedelta(minutes=5),
        payload_json=payload or {},
    )
    return row, browser


def challenge_attempt(challenge_id):
    StaffChallenge.objects.filter(id=challenge_id, consumed_at__isnull=True).update(
        attempts=F("attempts") + 1
    )


def locked_challenge(request, challenge_id, purpose):
    row = StaffChallenge.objects.select_for_update().filter(id=challenge_id).first()
    browser = request.COOKIES.get(CHALLENGE_COOKIE, "")
    if (
        row is None
        or row.purpose != purpose
        or row.consumed_at is not None
        or row.expires_at <= utc_now()
        or row.attempts > 5
        or not browser
        or not constant_time_compare(row.secret_digest, digest(browser))
    ):
        raise TaskillerAPIError(401, "admin_challenge_invalid", "Expired or invalid MFA challenge")
    return row


def verify_factor(enrollment, code, secret=None, recovery=True):
    # Caller holds the enrollment row lock; a TOTP time step or recovery code can
    # be consumed once across login, enrollment and step-up requests.
    if len(code) == 6 and code.isdecimal():
        totp = pyotp.TOTP(secret or decrypt(enrollment.mfa_secret_encrypted))
        now = utc_now()
        current_step = int(now.timestamp()) // 30
        for offset in (-1, 0, 1):
            step = current_step + offset
            if step > enrollment.last_totp_step and totp.verify(code, for_time=step * 30):
                enrollment.last_totp_step = step
                enrollment.updated_at = now
                enrollment.save(update_fields=["last_totp_step", "updated_at"])
                return True
    if recovery:
        normalized = code.replace("-", "").upper()
        row = (
            StaffRecoveryCode.objects.select_for_update()
            .filter(
                enrollment=enrollment,
                code_digest=digest(normalized),
                used_at__isnull=True,
            )
            .first()
        )
        if row:
            row.used_at = utc_now()
            row.save(update_fields=["used_at"])
            return True
    return False


def me(session):
    enrollment = session.enrollment
    user = enrollment.user
    return {
        "staffId": str(enrollment.id),
        "username": user.get_username(),
        "displayName": user.get_full_name() or user.get_username(),
        "capabilities": effective_capabilities(user),
        "roles": [
            name.removeprefix(GROUP_PREFIX)
            for name in user.groups.filter(
                name__startswith=GROUP_PREFIX,
            ).values_list("name", flat=True)
        ],
        "expiresAt": session.expires_at,
        "idleExpiresAt": min(
            session.expires_at,
            session.last_seen_at + timedelta(minutes=30),
        ),
        "mfaVerifiedAt": session.mfa_verified_at,
        "version": enrollment.version,
    }


class PublicAdminAPIView(AdminAPIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)


class CsrfView(PublicAdminAPIView):
    @extend_schema(operation_id="adminCsrf", auth=[], responses=S.CsrfResponse, tags=["Staff auth"])
    def get(self, request):
        return csrf_response(request, Response({}))


class LoginView(PublicAdminAPIView):
    @extend_schema(
        operation_id="adminLogin",
        auth=[],
        request=S.LoginRequest,
        responses=S.ChallengeResponse,
        tags=["Staff auth"],
    )
    def post(self, request):
        data = body(S.LoginRequest, request)
        throttle(request, "login-ip")
        throttle(request, "login-user", data["username"])
        user = authenticate(
            request=request._request, username=data["username"], password=data["password"]
        )
        enrollment = (
            StaffEnrollment.objects.filter(user=user, enabled=True).first() if user else None
        )
        if (
            not user
            or not user.is_staff
            or not user.is_active
            or not enrollment
            or not enrollment.mfa_secret_encrypted
        ):
            raise TaskillerAPIError(401, "admin_credentials_invalid", "Staff login failed")
        row, browser = challenge(enrollment, "login", {"authHash": user.get_session_auth_hash()})
        response = Response({"challengeId": row.id, "expiresAt": row.expires_at, "next": "mfa"})
        set_cookie(response, CHALLENGE_COOKIE, browser, 300)
        return response


class MfaView(PublicAdminAPIView):
    @extend_schema(
        operation_id="adminMfa",
        auth=[],
        request=S.MfaRequest,
        responses=S.StaffMeResponse,
        tags=["Staff auth"],
    )
    def post(self, request):
        data = body(S.MfaRequest, request)
        throttle(request, "mfa")
        challenge_attempt(data["challengeId"])
        with transaction.atomic(), owner_lock():
            pending = locked_challenge(request, data["challengeId"], "login")
            enrollment = (
                StaffEnrollment.objects.select_for_update()
                .select_related("user")
                .get(id=pending.enrollment_id)
            )
            if (
                not enrollment.enabled
                or not enrollment.user.is_active
                or not enrollment.user.is_staff
                or not constant_time_compare(
                    pending.payload_json.get("authHash", ""),
                    enrollment.user.get_session_auth_hash(),
                )
                or not verify_factor(enrollment, data["code"])
            ):
                raise TaskillerAPIError(401, "admin_mfa_invalid", "MFA verification failed")
            pending.consumed_at = utc_now()
            pending.save(update_fields=["consumed_at"])
            session, token = new_session(enrollment)
            record(
                request,
                "auth.login",
                target_type="staff",
                target_id=enrollment.id,
                actor_id=enrollment.id,
            )
        response = Response(me(session))
        set_cookie(response, STAFF_COOKIE, token, 8 * 3600)
        clear_cookie(response, CHALLENGE_COOKIE)
        return csrf_response(request, response, rotate=True)


class MeView(AdminAPIView):
    @extend_schema(operation_id="adminMe", responses=S.StaffMeResponse, tags=["Staff auth"])
    def get(self, request):
        return Response(me(request.auth))


class LogoutView(AdminAPIView):
    @extend_schema(operation_id="adminLogout", responses={204: None}, tags=["Staff auth"])
    def post(self, request):
        with transaction.atomic():
            StaffSession.objects.filter(id=request.auth.id).update(revoked_at=utc_now())
            record(
                request, "auth.logout", target_type="staff", target_id=request.auth.enrollment_id
            )
        response = Response(status=204)
        clear_cookie(response, STAFF_COOKIE)
        clear_cookie(response, CHALLENGE_COOKIE)
        return csrf_response(request, response, rotate=True)


class StepUpView(AdminAPIView):
    @extend_schema(
        operation_id="adminStepUp",
        request=S.StepUpRequest,
        responses=S.StaffMeResponse,
        tags=["Staff auth"],
    )
    def post(self, request):
        data = body(S.StepUpRequest, request)
        throttle(request, "step-up", str(request.auth.enrollment_id))
        with transaction.atomic(), owner_lock():
            enrollment = (
                StaffEnrollment.objects.select_for_update()
                .select_related("user")
                .get(id=request.auth.enrollment_id)
            )
            session = StaffSession.objects.select_for_update().get(id=request.auth.id)
            if (
                session.revoked_at
                or session.expires_at <= utc_now()
                or not enrollment.enabled
                or not enrollment.user.is_active
                or not enrollment.user.is_staff
                or not enrollment.mfa_secret_encrypted
                or session.last_seen_at <= utc_now() - timedelta(minutes=30)
                or not constant_time_compare(session.auth_hash, auth_hash(enrollment))
            ):
                raise TaskillerAPIError(401, "admin_auth_required", "Staff session revoked")
            if not verify_factor(enrollment, data["code"]):
                raise TaskillerAPIError(401, "admin_mfa_invalid", "MFA verification failed")
            token = secrets.token_urlsafe(48)
            session.token_digest = digest(token)
            session.mfa_verified_at = utc_now()
            session.last_seen_at = utc_now()
            session.version += 1
            session.save(
                update_fields=["token_digest", "mfa_verified_at", "last_seen_at", "version"]
            )
            record(request, "auth.step_up", target_type="staff", target_id=enrollment.id)
        response = Response(me(session))
        set_cookie(
            response,
            STAFF_COOKIE,
            token,
            max(0, int((session.expires_at - utc_now()).total_seconds())),
        )
        return csrf_response(request, response, rotate=True)


class EnrollView(PublicAdminAPIView):
    @extend_schema(
        operation_id="adminEnroll",
        auth=[],
        request=S.EnrollmentRequest,
        responses=S.EnrollmentChallengeResponse,
        tags=["Staff auth"],
    )
    def post(self, request):
        data = body(S.EnrollmentRequest, request)
        throttle(request, "enroll")
        with transaction.atomic(), owner_lock():
            invitation = (
                StaffChallenge.objects.select_for_update()
                .filter(
                    purpose="enrollment",
                    secret_digest=digest(data["invitationToken"]),
                    consumed_at__isnull=True,
                    expires_at__gt=utc_now(),
                )
                .first()
            )
            if invitation is None:
                raise TaskillerAPIError(
                    401, "admin_invitation_invalid", "Invitation expired or invalid"
                )
            enrollment = (
                StaffEnrollment.objects.select_for_update()
                .select_related("user")
                .get(id=invitation.enrollment_id)
            )
            user = enrollment.user
            if (
                not enrollment.enabled
                or not user.is_active
                or not user.is_staff
                or enrollment.mfa_secret_encrypted
            ):
                raise TaskillerAPIError(
                    401, "admin_invitation_invalid", "Invitation is no longer usable"
                )
            if user.has_usable_password():
                if not user.check_password(data["password"]):
                    raise TaskillerAPIError(
                        401, "admin_credentials_invalid", "Staff password verification failed"
                    )
            else:
                if len(data["password"]) < 12:
                    raise TaskillerAPIError(
                        422,
                        "validation_error",
                        "New staff passwords require at least 12 characters",
                    )
                try:
                    validate_password(data["password"], user=user)
                except ValidationError as exc:
                    raise TaskillerAPIError(
                        422, "validation_error", "Password does not meet policy"
                    ) from exc
                user.set_password(data["password"])
                user.save(update_fields=["password"])
            secret = pyotp.random_base32()
            pending, browser = challenge(
                enrollment,
                "enroll_verify",
                {
                    "secret": encrypt(secret),
                    "authHash": user.get_session_auth_hash(),
                    "enrollmentVersion": enrollment.version,
                },
            )
            invitation.consumed_at = utc_now()
            invitation.save(update_fields=["consumed_at"])
            record(
                request,
                "auth.enrollment_started",
                target_type="staff",
                target_id=enrollment.id,
                actor_id=enrollment.id,
            )
        response = Response(
            {
                "challengeId": pending.id,
                "expiresAt": pending.expires_at,
                "next": "enroll_verify",
                "secret": secret,
                "provisioningUri": pyotp.TOTP(secret).provisioning_uri(
                    name=user.get_username(), issuer_name="Taskiller Staff"
                ),
            }
        )
        set_cookie(response, CHALLENGE_COOKIE, browser, 300)
        return response


class EnrollConfirmView(PublicAdminAPIView):
    @extend_schema(
        operation_id="adminEnrollConfirm",
        auth=[],
        request=S.MfaRequest,
        responses=S.EnrollmentResponse,
        tags=["Staff auth"],
    )
    def post(self, request):
        data = body(S.MfaRequest, request)
        throttle(request, "enroll-confirm")
        challenge_attempt(data["challengeId"])
        with transaction.atomic(), owner_lock():
            pending = locked_challenge(request, data["challengeId"], "enroll_verify")
            enrollment = (
                StaffEnrollment.objects.select_for_update()
                .select_related("user")
                .get(id=pending.enrollment_id)
            )
            secret = decrypt(pending.payload_json["secret"])
            if (
                not enrollment.enabled
                or not enrollment.user.is_staff
                or not enrollment.user.is_active
                or enrollment.mfa_secret_encrypted
                or pending.payload_json.get("enrollmentVersion") != enrollment.version
                or not constant_time_compare(
                    pending.payload_json.get("authHash", ""),
                    enrollment.user.get_session_auth_hash(),
                )
                or not verify_factor(enrollment, data["code"], secret, recovery=False)
            ):
                raise TaskillerAPIError(
                    401, "admin_mfa_invalid", "Enrollment MFA verification failed"
                )
            enrollment.mfa_secret_encrypted = encrypt(secret)
            enrollment.version += 1
            enrollment.save(update_fields=["mfa_secret_encrypted", "version", "updated_at"])
            pending.consumed_at = utc_now()
            pending.save(update_fields=["consumed_at"])
            codes = [secrets.token_hex(12).upper() for _ in range(10)]
            StaffRecoveryCode.objects.bulk_create(
                [
                    StaffRecoveryCode(enrollment=enrollment, code_digest=digest(code))
                    for code in codes
                ]
            )
            record(
                request,
                "auth.enrolled",
                target_type="staff",
                target_id=enrollment.id,
                actor_id=enrollment.id,
            )
        response = Response({"enrolled": True, "recoveryCodes": codes})
        clear_cookie(response, CHALLENGE_COOKIE)
        return csrf_response(request, response, rotate=True)


urlpatterns = [
    path("auth/csrf", CsrfView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/mfa", MfaView.as_view()),
    path("auth/logout", LogoutView.as_view()),
    path("auth/step-up", StepUpView.as_view()),
    path("auth/enroll", EnrollView.as_view()),
    path("auth/enroll/confirm", EnrollConfirmView.as_view()),
    path("me", MeView.as_view()),
]
