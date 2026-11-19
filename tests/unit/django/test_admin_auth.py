# ruff: noqa: E402
"""Isolated staff authentication tests; database workflows live in integration."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.test import override_settings
from django.urls import include, path
from rest_framework.response import Response
from rest_framework.test import APIClient

from taskiller.django_api.admin_api import audit, permissions, serializers
from taskiller.django_api.admin_api import auth_views as views
from taskiller.django_api.admin_api import authentication as auth
from taskiller.django_api.errors import TaskillerAPIError

ORIGIN = "https://console.example.test"
NOW = datetime(2026, 11, 19, 12, 0, 10, tzinfo=UTC)


class WriteProbe(auth.AdminAPIView):
    writes = True

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("api/v1/admin/", include(views.urlpatterns)),
    path("api/v1/admin/write-probe", WriteProbe.as_view()),
]


@pytest.fixture(autouse=True)
def isolated_console(monkeypatch):
    # Settings have already loaded .env at collection; override them as well as
    # clearing operator bootstrap credentials so these tests never inherit them.
    for name in ("USERNAME", "EMAIL", "PASSWORD"):
        monkeypatch.delenv(f"TASKILLER_ADMIN_{name}", raising=False)
    monkeypatch.setattr(audit, "record", Mock())
    monkeypatch.setattr(auth, "utc_now", lambda: NOW)
    monkeypatch.setattr(views, "utc_now", lambda: NOW)
    monkeypatch.setattr(permissions, "utc_now", lambda: NOW)
    with override_settings(
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[],
        ALLOWED_HOSTS=["testserver"],
        SECRET_KEY="isolated-staff-unit-test-secret",
        ADMIN_CONSOLE_ENABLED=True,
        ADMIN_CONSOLE_WRITES_ENABLED=True,
        ADMIN_CONSOLE_ORIGINS=[ORIGIN],
        CSRF_TRUSTED_ORIGINS=[ORIGIN],
        ADMIN_CONSOLE_ENCRYPTION_KEYS=[Fernet.generate_key().decode()],
        ADMIN_CONSOLE_COOKIE_SECURE=True,
        CSRF_USE_SESSIONS=False,
    ):
        yield


@pytest.fixture
def browser():
    return APIClient(enforce_csrf_checks=True)


def bootstrap(browser):
    response = browser.get("/api/v1/admin/auth/csrf", secure=True)
    assert response.status_code == 200
    return response.data["csrfToken"]


def post(browser, endpoint, payload, token, **headers):
    return browser.post(
        f"/api/v1/admin/{endpoint}",
        payload,
        format="json",
        secure=True,
        HTTP_ORIGIN=ORIGIN,
        HTTP_X_CSRFTOKEN=token,
        **headers,
    )


@pytest.mark.parametrize(
    "endpoint", ["auth/login", "auth/mfa", "auth/enroll", "auth/enroll/confirm"]
)
@pytest.mark.parametrize("failure", ["missing-cookie", "missing-header", "malformed", "mismatch"])
def test_anonymous_posts_require_dedicated_csrf(browser, endpoint, failure):
    token = bootstrap(browser)
    if failure == "missing-cookie":
        del browser.cookies[auth.CSRF_COOKIE]
    elif failure == "missing-header":
        token = ""
    elif failure == "malformed":
        browser.cookies[auth.CSRF_COOKIE] = "malformed"
    else:
        token = "z" * 32
    response = post(browser, endpoint, {}, token)
    assert response.status_code == 403
    assert response.data["code"] == "admin_csrf_failed"


@pytest.mark.parametrize(
    "origin",
    [None, "null", "https://evil.example.test", ORIGIN + "/", "http://console.example.test"],
)
@pytest.mark.parametrize(
    "endpoint",
    ["auth/login", "auth/mfa", "auth/enroll", "auth/enroll/confirm", "auth/logout", "auth/step-up"],
)
def test_strict_origin_is_required_even_with_valid_csrf(browser, origin, endpoint):
    token = bootstrap(browser)
    headers = {"HTTP_X_CSRFTOKEN": token}
    if origin is not None:
        headers["HTTP_ORIGIN"] = origin
    response = browser.post(
        f"/api/v1/admin/{endpoint}",
        {},
        format="json",
        secure=True,
        **headers,
    )
    assert response.status_code == 403
    assert response.data["code"] == "admin_origin_forbidden"


def test_product_csrf_cookie_cannot_authorize_staff_login(browser):
    token = bootstrap(browser)
    value = browser.cookies[auth.CSRF_COOKIE].value
    del browser.cookies[auth.CSRF_COOKIE]
    browser.cookies["csrftoken"] = value
    response = post(browser, "auth/login", {}, token)
    assert response.status_code == 403


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("auth/login", {"username": "operator"}),
        ("auth/mfa", {"challengeId": "not-a-uuid", "code": "123456"}),
        ("auth/enroll", {"invitationToken": "abc", "password": ""}),
        ("auth/enroll/confirm", {"challengeId": str(uuid4())}),
    ],
)
def test_real_request_serializers_reject_invalid_auth_bodies(browser, endpoint, payload):
    response = post(browser, endpoint, payload, bootstrap(browser))
    assert response.status_code == 422
    assert response.data["code"] == "validation_error"
    assert "password" not in str(response.data.get("detail", ""))


@pytest.mark.parametrize(
    "serializer,payload",
    [
        (serializers.LoginRequest, {"username": "x" * 151, "password": "valid"}),
        (serializers.LoginRequest, {"username": "operator", "password": "x" * 1025}),
        (serializers.MfaRequest, {"challengeId": str(uuid4()), "code": "x" * 65}),
        (serializers.StepUpRequest, {"code": ""}),
        (serializers.EnrollmentRequest, {"invitationToken": "x" * 201, "password": "x" * 12}),
    ],
)
def test_auth_serializer_bounds(serializer, payload):
    assert not serializer(data=payload).is_valid()


@pytest.mark.parametrize("credential", ["Bearer product.jwt.signature", "Basic anything"])
def test_authorization_header_is_rejected_before_staff_lookup(browser, monkeypatch, credential):
    lookup = Mock(side_effect=AssertionError("must not query staff sessions"))
    monkeypatch.setattr(auth.StaffSession.objects, "select_related", lookup)
    browser.cookies[auth.STAFF_COOKIE] = "opaque-staff-token"
    response = browser.get("/api/v1/admin/me", HTTP_AUTHORIZATION=credential)
    assert response.status_code == 401
    lookup.assert_not_called()


@pytest.mark.parametrize("cookie", ["sessionid", auth.CHALLENGE_COOKIE, "taskiller_refresh"])
def test_other_cookie_names_never_authenticate_staff(browser, monkeypatch, cookie):
    lookup = Mock(side_effect=AssertionError("must not query staff sessions"))
    monkeypatch.setattr(auth.StaffSession.objects, "select_related", lookup)
    browser.cookies[cookie] = "unrelated-credential"
    response = browser.get("/api/v1/admin/me")
    assert response.status_code == 401
    lookup.assert_not_called()


def test_csrf_bootstrap_cookie_scope_and_response_headers(browser):
    response = browser.get("/api/v1/admin/auth/csrf", secure=True)
    cookie = response.cookies[auth.CSRF_COOKIE]
    assert cookie["path"] == "/admin"
    assert cookie["secure"]
    assert not cookie["httponly"]
    assert cookie["samesite"] == "Lax"
    assert not cookie["domain"]
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert "noindex" in response["X-Robots-Tag"]
    assert response.data["csrfToken"] != cookie.value


@pytest.mark.parametrize(
    "endpoint,method", [("auth/csrf", "get"), ("me", "get"), ("auth/login", "post")]
)
def test_disabled_console_has_no_auth_surface(browser, endpoint, method):
    with override_settings(ADMIN_CONSOLE_ENABLED=False):
        response = getattr(browser, method)(f"/api/v1/admin/{endpoint}")
    assert response.status_code == 404
    assert response.data["code"] == "admin_disabled"


def test_disabled_writes_does_not_disable_csrf_bootstrap(browser):
    with override_settings(ADMIN_CONSOLE_WRITES_ENABLED=False):
        assert browser.get("/api/v1/admin/auth/csrf").status_code == 200
        response = browser.post("/api/v1/admin/write-probe", {}, format="json")
    assert response.status_code == 403
    assert response.data["code"] == "admin_writes_disabled"


def test_mfa_cipher_uses_ephemeral_keys_and_supports_rotation():
    secret = pyotp.random_base32()
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    with override_settings(ADMIN_CONSOLE_ENCRYPTION_KEYS=[old_key]):
        encrypted = views.encrypt(secret)
        assert secret not in encrypted
        assert views.encrypt(secret) != encrypted
        assert views.decrypt(encrypted) == secret
    with override_settings(ADMIN_CONSOLE_ENCRYPTION_KEYS=[new_key, old_key]):
        assert views.decrypt(encrypted) == secret
        replacement = views.encrypt(secret)
        assert Fernet(new_key.encode()).decrypt(replacement.encode()).decode() == secret
    with override_settings(ADMIN_CONSOLE_ENCRYPTION_KEYS=[new_key]):
        with pytest.raises(TaskillerAPIError) as error:
            views.decrypt(encrypted)
        assert error.value.code == "admin_mfa_invalid"


def test_missing_encryption_configuration_fails_closed():
    with override_settings(ADMIN_CONSOLE_ENCRYPTION_KEYS=[]):
        with pytest.raises(TaskillerAPIError) as error:
            views.encrypt("sensitive-secret")
    assert error.value.status_code == 503


@pytest.mark.parametrize("ciphertext", ["plaintext-secret", "gAAAA-invalid", ""])
def test_invalid_ciphertext_never_returns_plaintext(ciphertext):
    with pytest.raises(TaskillerAPIError) as error:
        views.decrypt(ciphertext)
    assert error.value.code == "admin_mfa_invalid"


def test_totp_time_step_is_consumed_once_without_database(monkeypatch):
    secret = pyotp.random_base32()
    enrollment = SimpleNamespace(
        mfa_secret_encrypted=views.encrypt(secret),
        last_totp_step=-1,
        save=Mock(),
    )
    code = pyotp.TOTP(secret).at(NOW)
    assert views.verify_factor(enrollment, code, recovery=False)
    assert enrollment.last_totp_step == int(NOW.timestamp()) // 30
    assert not views.verify_factor(enrollment, code, recovery=False)
    enrollment.save.assert_called_once()


def test_totp_outside_window_is_rejected():
    secret = pyotp.random_base32()
    enrollment = SimpleNamespace(
        mfa_secret_encrypted=views.encrypt(secret),
        last_totp_step=-1,
        save=Mock(),
    )
    # Ensure this randomly selected secret does not have a coincidental OTP collision.
    totp = pyotp.TOTP(secret)
    valid = {totp.at(NOW + timedelta(seconds=offset)) for offset in (-30, 0, 30)}
    code = next(
        totp.at(NOW - timedelta(seconds=age))
        for age in range(90, 901, 30)
        if totp.at(NOW - timedelta(seconds=age)) not in valid
    )
    assert not views.verify_factor(enrollment, code, recovery=False)
    enrollment.save.assert_not_called()


def test_session_hash_tracks_password_version_and_capability_changes(monkeypatch):
    user = SimpleNamespace(get_session_auth_hash=Mock(return_value="password-hash"))
    enrollment = SimpleNamespace(user=user, version=1)
    capabilities = Mock(return_value=["view_users"])
    monkeypatch.setattr(auth, "effective_capabilities", capabilities)
    original = auth.auth_hash(enrollment)
    user.get_session_auth_hash.return_value = "new-password-hash"
    assert auth.auth_hash(enrollment) != original
    user.get_session_auth_hash.return_value = "password-hash"
    enrollment.version += 1
    assert auth.auth_hash(enrollment) != original
    enrollment.version = 1
    capabilities.return_value = ["view_overview"]
    assert auth.auth_hash(enrollment) != original


def test_enrollment_can_verify_existing_shorter_django_password():
    serializer = serializers.EnrollmentRequest(
        data={"invitationToken": "valid", "password": "Existing10!"}
    )
    assert serializer.is_valid()
