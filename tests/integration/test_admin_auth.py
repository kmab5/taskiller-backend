# ruff: noqa: E402
"""Real serializer/cookie/MFA workflows against disposable PostgreSQL only."""

from __future__ import annotations

import os
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import psycopg
import pyotp
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from taskiller.auth.security import create_access_token
from taskiller.core.config import Settings
from taskiller.django_api import authentication as product_auth
from taskiller.django_api import middleware, runtime, security
from taskiller.django_api.admin_api import auth_views as views
from taskiller.django_api.admin_api import authentication as auth
from taskiller.django_api.admin_api import permissions as policy
from taskiller.django_api.authentication import TaskillerBearerAuthentication
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_domain import models as domain

pytestmark = pytest.mark.integration
ORIGIN = "https://console.example.test"
PASSWORD = "CI-operator-individual-password-597!"
BASE = "/api/v1/admin/"


class ProductProbe(APIView):
    authentication_classes = (TaskillerBearerAuthentication,)

    def get(self, request):
        return Response({"id": str(request.user.id)})


class StaffWriteProbe(auth.AdminAPIView):
    capability = "manage_accounts"
    step_up = True
    writes = True

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("api/v1/admin/", include(views.urlpatterns)),
    path("api/v1/admin/write-probe", StaffWriteProbe.as_view()),
    path("api/v1/product-probe", ProductProbe.as_view()),
]


@pytest.fixture(autouse=True)
def isolated_console(monkeypatch, integration_transaction):
    for name in ("USERNAME", "EMAIL", "PASSWORD"):
        monkeypatch.delenv(f"TASKILLER_ADMIN_{name}", raising=False)
    config = Settings(
        _env_file=None,
        env="test",
        jwt_secret="ci-product-jwt-secret-independent-597",
        token_hash_secret="ci-product-token-hmac-independent-913",
        cors_origins=[ORIGIN],
        allowed_hosts=["testserver"],
        email_delivery_mode="safe_log",
        rate_limit_test_mode=False,
        trust_forwarded_for=False,
    )
    monkeypatch.setattr(runtime, "taskiller_settings", lambda: config)
    monkeypatch.setattr(product_auth, "taskiller_settings", lambda: config)
    monkeypatch.setattr(security, "taskiller_settings", lambda: config)
    monkeypatch.setattr(middleware, "get_settings", lambda: config)
    with override_settings(
        ROOT_URLCONF=__name__,
        SECRET_KEY="isolated-staff-integration-test-secret",
        ALLOWED_HOSTS=["testserver"],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
        ],
        AUTHENTICATION_BACKENDS=["django.contrib.auth.backends.ModelBackend"],
        PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"],
        ADMIN_CONSOLE_ENABLED=True,
        ADMIN_CONSOLE_WRITES_ENABLED=True,
        ADMIN_CONSOLE_ORIGINS=[ORIGIN],
        CSRF_TRUSTED_ORIGINS=[ORIGIN],
        ADMIN_CONSOLE_ENCRYPTION_KEYS=[Fernet.generate_key().decode()],
        ADMIN_CONSOLE_COOKIE_SECURE=True,
        CSRF_USE_SESSIONS=False,
        SESSION_ENGINE="django.contrib.sessions.backends.db",
    ):
        policy.ensure_roles()
        yield config


@pytest.fixture
def clock(monkeypatch):
    current = timezone.now().replace(second=10, microsecond=0)
    state = SimpleNamespace(now=current)
    for module in (auth, views, policy):
        monkeypatch.setattr(module, "utc_now", lambda: state.now)
    return state


@pytest.fixture
def operator(clock):
    user = get_user_model().objects.create_user(
        username=f"staff-{uuid4()}",
        password=PASSWORD,
        is_staff=True,
    )
    user.groups.add(Group.objects.get(name=f"{policy.GROUP_PREFIX}Owner"))
    secret = pyotp.random_base32()
    enrollment = domain.StaffEnrollment.objects.create(
        user=user,
        mfa_secret_encrypted=views.encrypt(secret),
    )
    return SimpleNamespace(user=user, enrollment=enrollment, secret=secret)


@pytest.fixture
def browser():
    return APIClient(enforce_csrf_checks=True)


def csrf(browser):
    response = browser.get(BASE + "auth/csrf", secure=True)
    assert response.status_code == 200
    return response.data["csrfToken"]


def post(browser, endpoint, payload, token=None):
    return browser.post(
        BASE + endpoint,
        payload,
        format="json",
        secure=True,
        HTTP_ORIGIN=ORIGIN,
        HTTP_X_CSRFTOKEN=token or csrf(browser),
    )


def password_stage(browser, operator):
    response = post(
        browser,
        "auth/login",
        {
            "username": operator.user.username,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.data
    return str(response.data["challengeId"])


def complete_login(browser, operator, clock, code=None):
    challenge_id = password_stage(browser, operator)
    response = post(
        browser,
        "auth/mfa",
        {
            "challengeId": challenge_id,
            "code": code or pyotp.TOTP(operator.secret).at(clock.now),
        },
    )
    assert response.status_code == 200, response.data
    return response


def session_for(browser):
    return domain.StaffSession.objects.get(
        token_digest=auth.digest(browser.cookies[auth.STAFF_COOKIE].value)
    )


def assert_problem(response, status, code):
    assert response.status_code == status, response.data
    assert response.data["code"] == code
    assert "no-store" in response["Cache-Control"]


def test_full_login_requires_totp_and_stores_only_credential_digests(browser, operator, clock):
    challenge_id = password_stage(browser, operator)
    challenge = domain.StaffChallenge.objects.get(pk=challenge_id)
    browser_secret = browser.cookies[auth.CHALLENGE_COOKIE].value
    assert challenge.secret_digest == auth.digest(browser_secret)
    assert browser_secret not in str(challenge.payload_json)
    assert not domain.StaffSession.objects.filter(enrollment=operator.enrollment).exists()
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")
    before_csrf = browser.cookies[auth.CSRF_COOKIE].value
    response = post(
        browser,
        "auth/mfa",
        {
            "challengeId": challenge_id,
            "code": pyotp.TOTP(operator.secret).at(clock.now),
        },
    )
    assert response.status_code == 200
    challenge.refresh_from_db()
    assert challenge.consumed_at == clock.now
    assert response.data["staffId"] == str(operator.enrollment.id)
    assert set(response.data["capabilities"]) == policy.CAPABILITIES
    session = session_for(browser)
    assert session.expires_at == clock.now + timedelta(hours=8)
    assert session.mfa_verified_at == clock.now
    assert session.token_digest != browser.cookies[auth.STAFF_COOKIE].value
    assert browser.cookies[auth.CSRF_COOKIE].value != before_csrf
    cookie = response.cookies[auth.STAFF_COOKIE]
    assert cookie["path"] == "/admin" and cookie["secure"] and cookie["httponly"]
    assert cookie["samesite"] == "Lax" and not cookie["domain"]
    assert response.cookies[auth.CHALLENGE_COOKIE]["max-age"] == 0
    assert browser.get(BASE + "me").status_code == 200
    assert operator.secret not in str(response.data)
    login_audit = domain.AdminAuditRecord.objects.get(
        action="auth.login", target_id=str(operator.enrollment.id)
    )
    assert login_audit.actor_id == str(operator.enrollment.id)
    assert operator.secret not in str(login_audit.changes_json)


def test_django_admin_session_is_not_a_staff_console_session(browser, operator):
    browser.force_login(operator.user)
    assert "sessionid" in browser.cookies
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_valid_product_jwt_is_rejected_by_console(browser, isolated_console):
    now = timezone.now()
    user = domain.TaskillerUser.objects.create(
        id=uuid4(),
        email=f"product-{uuid4()}@example.test",
        password_hash="ci-only",
        password_changed_at=now,
        is_active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )
    session = domain.AuthSession.objects.create(
        id=uuid4(),
        user=user,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    token, _expiry = create_access_token(user.id, session.id, isolated_console)
    browser.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert browser.get("/api/v1/product-probe").status_code == 200
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_staff_cookie_is_not_product_authentication(browser, operator, clock):
    complete_login(browser, operator, clock)
    assert browser.get("/api/v1/product-probe").status_code == 401


def test_pending_challenge_is_browser_bound_and_not_a_full_session(browser, operator, clock):
    challenge_id = password_stage(browser, operator)
    stolen = APIClient(enforce_csrf_checks=True)
    response = post(
        stolen,
        "auth/mfa",
        {
            "challengeId": challenge_id,
            "code": pyotp.TOTP(operator.secret).at(clock.now),
        },
    )
    assert_problem(response, 401, "admin_challenge_invalid")
    browser.cookies[auth.STAFF_COOKIE] = browser.cookies[auth.CHALLENGE_COOKIE].value
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_challenge_and_totp_cannot_be_replayed(browser, operator, clock):
    challenge_id = password_stage(browser, operator)
    challenge_cookie = browser.cookies[auth.CHALLENGE_COOKIE].value
    code = pyotp.TOTP(operator.secret).at(clock.now)
    assert post(browser, "auth/mfa", {"challengeId": challenge_id, "code": code}).status_code == 200
    browser.cookies[auth.CHALLENGE_COOKIE] = challenge_cookie
    assert_problem(
        post(browser, "auth/mfa", {"challengeId": challenge_id, "code": code}),
        401,
        "admin_challenge_invalid",
    )
    next_challenge = password_stage(browser, operator)
    assert_problem(
        post(browser, "auth/mfa", {"challengeId": next_challenge, "code": code}),
        401,
        "admin_mfa_invalid",
    )
    assert domain.StaffSession.objects.filter(enrollment=operator.enrollment).count() == 1


def test_recovery_code_is_hashed_normalized_and_single_use(browser, operator, clock):
    raw = "ABCD1234EF567890ABCD1234"
    row = domain.StaffRecoveryCode.objects.create(
        enrollment=operator.enrollment, code_digest=auth.digest(raw)
    )
    complete_login(browser, operator, clock, code="abcd-1234-ef56-7890-abcd-1234")
    row.refresh_from_db()
    assert row.used_at == clock.now
    assert row.code_digest != raw
    challenge_id = password_stage(browser, operator)
    assert_problem(
        post(browser, "auth/mfa", {"challengeId": challenge_id, "code": raw}),
        401,
        "admin_mfa_invalid",
    )


@pytest.mark.parametrize("mutation", ["expired", "consumed", "wrong-purpose", "exhausted"])
def test_invalid_challenge_state_never_creates_session(browser, operator, clock, mutation):
    challenge_id = password_stage(browser, operator)
    changes = {
        "expired": {"expires_at": clock.now},
        "consumed": {"consumed_at": clock.now},
        "wrong-purpose": {"purpose": "enroll_verify"},
        "exhausted": {"attempts": 5},
    }[mutation]
    domain.StaffChallenge.objects.filter(pk=challenge_id).update(**changes)
    response = post(
        browser,
        "auth/mfa",
        {"challengeId": challenge_id, "code": pyotp.TOTP(operator.secret).at(clock.now)},
    )
    assert_problem(response, 401, "admin_challenge_invalid")
    assert not domain.StaffSession.objects.filter(enrollment=operator.enrollment).exists()


@pytest.mark.parametrize("change", ["password", "disabled", "inactive", "not-staff"])
def test_password_challenge_rechecks_current_identity(browser, operator, clock, change):
    challenge_id = password_stage(browser, operator)
    if change == "disabled":
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(enabled=False)
    else:
        if change == "password":
            operator.user.set_password("replacement-password-for-ci-913!")
        elif change == "inactive":
            operator.user.is_active = False
        else:
            operator.user.is_staff = False
        operator.user.save()
    response = post(
        browser,
        "auth/mfa",
        {"challengeId": challenge_id, "code": pyotp.TOTP(operator.secret).at(clock.now)},
    )
    assert_problem(response, 401, "admin_mfa_invalid")


@pytest.mark.parametrize(
    "change", ["password", "version", "roles", "disabled", "inactive", "not-staff", "mfa-reset"]
)
def test_existing_session_is_revoked_after_identity_or_authority_changes(
    browser, operator, clock, change
):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    if change == "version":
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(version=2)
    elif change == "disabled":
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(enabled=False)
    elif change == "mfa-reset":
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(
            mfa_secret_encrypted=""
        )
    elif change == "roles":
        operator.user.groups.set([Group.objects.get(name=f"{policy.GROUP_PREFIX}Analyst")])
    else:
        if change == "password":
            operator.user.set_password("replacement-password-for-ci-913!")
        elif change == "inactive":
            operator.user.is_active = False
        else:
            operator.user.is_staff = False
        operator.user.save()
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")
    session.refresh_from_db()
    assert session.revoked_at == clock.now


@pytest.mark.parametrize("expiry", ["idle", "absolute", "revoked"])
def test_session_expiry_boundaries(browser, operator, clock, expiry):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    changes = {
        "idle": {"last_seen_at": clock.now - timedelta(minutes=30)},
        "absolute": {"expires_at": clock.now},
        "revoked": {"revoked_at": clock.now},
    }[expiry]
    domain.StaffSession.objects.filter(pk=session.id).update(**changes)
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_step_up_rotates_staff_and_csrf_credentials_without_extending_absolute_lifetime(
    browser, operator, clock
):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    old_token = browser.cookies[auth.STAFF_COOKIE].value
    old_csrf_cookie = browser.cookies[auth.CSRF_COOKIE].value
    clock.now += timedelta(minutes=6)
    assert_problem(post(browser, "write-probe", {}), 403, "admin_step_up_required")
    response = post(browser, "auth/step-up", {"code": pyotp.TOTP(operator.secret).at(clock.now)})
    assert response.status_code == 200
    assert browser.cookies[auth.STAFF_COOKIE].value != old_token
    assert browser.cookies[auth.CSRF_COOKIE].value != old_csrf_cookie
    refreshed = session_for(browser)
    assert refreshed.id == session.id and refreshed.version == session.version + 1
    assert refreshed.expires_at == session.expires_at
    assert refreshed.mfa_verified_at == clock.now
    assert post(browser, "write-probe", {}).status_code == 200
    stale = APIClient(enforce_csrf_checks=True)
    stale.cookies[auth.STAFF_COOKIE] = old_token
    assert_problem(stale.get(BASE + "me"), 401, "admin_auth_required")
    assert_problem(
        post(browser, "auth/step-up", {"code": pyotp.TOTP(operator.secret).at(clock.now)}),
        401,
        "admin_mfa_invalid",
    )


def test_logout_revokes_server_record_and_clears_cookies(browser, operator, clock):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    old_token = browser.cookies[auth.STAFF_COOKIE].value
    response = post(browser, "auth/logout", {})
    assert response.status_code == 204
    assert response.cookies[auth.STAFF_COOKIE]["max-age"] == 0
    session.refresh_from_db()
    assert session.revoked_at == clock.now
    browser.cookies[auth.STAFF_COOKIE] = old_token
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_explicit_private_permissions_do_not_allow_arbitrary_direct_grants(operator):
    operator.user.groups.clear()
    content_type = ContentType.objects.get_for_model(domain.StaffEnrollment)
    for capability in ("read_private", "manage_privacy", "manage_staff"):
        operator.user.user_permissions.add(
            Permission.objects.get(content_type=content_type, codename=f"console_{capability}")
        )
    assert policy.effective_capabilities(operator.user) == ["manage_privacy", "read_private"]
    foreign = Group.objects.create(name=f"unrelated-{uuid4()}")
    foreign.permissions.set(Permission.objects.filter(content_type=content_type))
    operator.user.groups.add(foreign)
    assert policy.effective_capabilities(operator.user) == ["manage_privacy", "read_private"]


def test_superuser_without_console_role_has_no_capabilities(operator):
    operator.user.groups.clear()
    operator.user.is_superuser = True
    operator.user.save(update_fields=["is_superuser"])
    assert policy.effective_capabilities(operator.user) == []


def test_unenrolled_owner_must_not_allow_last_enrolled_owner_removal(operator):
    """Regression: an invited identity with no MFA cannot serve as a surviving Owner."""
    other = get_user_model().objects.create_user(
        username=f"pending-{uuid4()}", password=PASSWORD, is_staff=True
    )
    other.groups.add(Group.objects.get(name=f"{policy.GROUP_PREFIX}Owner"))
    domain.StaffEnrollment.objects.create(user=other, mfa_secret_encrypted="")
    with transaction.atomic(), policy.owner_lock():
        with pytest.raises(TaskillerAPIError) as error:
            policy.ensure_not_last_owner(operator.enrollment)
    assert error.value.code == "admin_last_owner"


def test_enrollment_encrypts_secret_and_returns_recovery_codes_only_once(browser, operator, clock):
    domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(mfa_secret_encrypted="")
    invitation, invitation_token = views.challenge(operator.enrollment, "enrollment")
    response = post(
        browser,
        "auth/enroll",
        {
            "invitationToken": invitation_token,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    secret = response.data["secret"]
    assert secret in response.data["provisioningUri"]
    challenge_id = str(response.data["challengeId"])
    pending = domain.StaffChallenge.objects.get(pk=challenge_id)
    assert secret not in str(pending.payload_json)
    assert views.decrypt(pending.payload_json["secret"]) == secret
    invitation.refresh_from_db()
    assert invitation.consumed_at == clock.now
    assert not domain.StaffSession.objects.filter(enrollment=operator.enrollment).exists()
    repeated = post(
        browser,
        "auth/enroll",
        {
            "invitationToken": invitation_token,
            "password": PASSWORD,
        },
    )
    assert_problem(repeated, 401, "admin_invitation_invalid")
    challenge_cookie = browser.cookies[auth.CHALLENGE_COOKIE].value
    confirmation = post(
        browser,
        "auth/enroll/confirm",
        {
            "challengeId": challenge_id,
            "code": pyotp.TOTP(secret).at(clock.now),
        },
    )
    assert confirmation.status_code == 200
    codes = confirmation.data["recoveryCodes"]
    assert len(codes) == len(set(codes)) == 10
    operator.enrollment.refresh_from_db()
    assert secret not in operator.enrollment.mfa_secret_encrypted
    assert views.decrypt(operator.enrollment.mfa_secret_encrypted) == secret
    assert set(
        domain.StaffRecoveryCode.objects.filter(
            enrollment=operator.enrollment,
        ).values_list("code_digest", flat=True)
    ) == {auth.digest(code) for code in codes}
    browser.cookies[auth.CHALLENGE_COOKIE] = challenge_cookie
    repeated = post(
        browser,
        "auth/enroll/confirm",
        {
            "challengeId": challenge_id,
            "code": pyotp.TOTP(secret).at(clock.now),
        },
    )
    assert_problem(repeated, 401, "admin_challenge_invalid")
    assert "recoveryCodes" not in repeated.data
    operator.secret = secret
    # Enrollment consumed the current OTP; the next fresh time step can log in.
    clock.now += timedelta(seconds=30)
    complete_login(browser, operator, clock)


@pytest.mark.parametrize(
    "failure", ["wrong-password", "unknown-user", "not-staff", "inactive", "unenrolled", "disabled"]
)
def test_login_failures_have_generic_errors_and_no_challenge(browser, operator, failure):
    username, password = operator.user.username, PASSWORD
    if failure == "wrong-password":
        password = "incorrect-password"
    elif failure == "unknown-user":
        username = f"unknown-{uuid4()}"
    elif failure == "not-staff":
        operator.user.is_staff = False
        operator.user.save(update_fields=["is_staff"])
    elif failure == "inactive":
        operator.user.is_active = False
        operator.user.save(update_fields=["is_active"])
    elif failure == "unenrolled":
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(
            mfa_secret_encrypted=""
        )
    else:
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(enabled=False)
    response = post(browser, "auth/login", {"username": username, "password": password})
    assert_problem(response, 401, "admin_credentials_invalid")
    assert auth.CHALLENGE_COOKIE not in response.cookies
    assert not domain.StaffChallenge.objects.filter(enrollment=operator.enrollment).exists()
    assert password not in str(response.data)


@pytest.mark.parametrize(
    "endpoint", ["auth/login", "auth/mfa", "auth/enroll", "auth/enroll/confirm"]
)
def test_anonymous_csrf_rejection_does_not_create_auth_state(browser, operator, endpoint):
    response = browser.post(BASE + endpoint, {}, format="json", secure=True, HTTP_ORIGIN=ORIGIN)
    assert_problem(response, 403, "admin_csrf_failed")
    assert not domain.StaffSession.objects.filter(enrollment=operator.enrollment).exists()
    assert not domain.StaffChallenge.objects.filter(enrollment=operator.enrollment).exists()
    assert domain.AdminAuditRecord.objects.filter(
        action="security.denied", outcome="denied"
    ).exists()


def test_role_group_permission_changes_revoke_existing_hash(browser, operator, clock):
    complete_login(browser, operator, clock)
    owner = Group.objects.get(name=f"{policy.GROUP_PREFIX}Owner")
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(domain.StaffEnrollment),
        codename="console_manage_staff",
    )
    owner.permissions.remove(permission)
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_last_seen_throttle_and_absolute_expiry_do_not_slide(browser, operator, clock):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    clock.now += timedelta(seconds=30)
    assert browser.get(BASE + "me").status_code == 200
    session.refresh_from_db()
    assert session.last_seen_at == clock.now - timedelta(seconds=30)
    clock.now += timedelta(seconds=31)
    assert browser.get(BASE + "me").status_code == 200
    session.refresh_from_db()
    assert session.last_seen_at == clock.now
    assert session.expires_at == session.created_at + timedelta(hours=8)


def test_rollout_switches_preserve_logout_when_commands_are_disabled(browser, operator, clock):
    complete_login(browser, operator, clock)
    with override_settings(ADMIN_CONSOLE_WRITES_ENABLED=False):
        assert browser.get(BASE + "me").status_code == 200
        assert_problem(post(browser, "write-probe", {}), 403, "admin_writes_disabled")
        assert post(browser, "auth/logout", {}).status_code == 204
    with override_settings(ADMIN_CONSOLE_ENABLED=False):
        assert_problem(browser.get(BASE + "auth/csrf"), 404, "admin_disabled")
        assert_problem(browser.get(BASE + "me"), 404, "admin_disabled")


def test_mfa_rate_limit_is_database_backed(browser, operator, clock, monkeypatch, isolated_console):
    limited = isolated_console.model_copy(update={"rate_limit_test_mode": True})
    monkeypatch.setattr(security, "taskiller_settings", lambda: limited)
    challenge_id = password_stage(browser, operator)
    for _attempt in range(5):
        response = post(browser, "auth/mfa", {"challengeId": challenge_id, "code": "not-a-factor"})
        assert_problem(response, 401, "admin_mfa_invalid")
    response = post(
        browser,
        "auth/mfa",
        {
            "challengeId": challenge_id,
            "code": pyotp.TOTP(operator.secret).at(clock.now),
        },
    )
    assert_problem(response, 429, "rate_limit_exceeded")
    assert int(response["Retry-After"]) > 0
    assert domain.RateLimitBucket.objects.filter(scope="staff:mfa").exists()
    assert not domain.StaffSession.objects.filter(enrollment=operator.enrollment).exists()


@pytest.mark.parametrize(
    "change", ["not-staff", "inactive", "password", "capabilities", "idle", "revoked"]
)
def test_step_up_rechecks_identity_changed_after_initial_authentication(
    browser, operator, clock, monkeypatch, change
):
    """Regression: do not issue a rotated credential to a newly disabled staff user."""
    complete_login(browser, operator, clock)
    previous = browser.cookies[auth.STAFF_COOKIE].value
    clock.now += timedelta(seconds=30)
    select_for_update = domain.StaffEnrollment.objects.select_for_update

    def disable_before_lock(*args, **kwargs):
        # Simulate a disablement committed after initial authentication but before
        # the step-up transaction locks and reloads the enrollment and user.
        if change == "not-staff":
            get_user_model().objects.filter(pk=operator.user.pk).update(is_staff=False)
        elif change == "inactive":
            get_user_model().objects.filter(pk=operator.user.pk).update(is_active=False)
        elif change == "password":
            operator.user.set_password("replacement-password-after-authentication-913!")
            operator.user.save(update_fields=["password"])
        elif change == "capabilities":
            operator.user.groups.set([Group.objects.get(name=f"{policy.GROUP_PREFIX}Analyst")])
        elif change == "idle":
            domain.StaffSession.objects.filter(token_digest=auth.digest(previous)).update(
                last_seen_at=clock.now - timedelta(minutes=30),
            )
        else:
            domain.StaffSession.objects.filter(token_digest=auth.digest(previous)).update(
                revoked_at=clock.now,
            )
        return select_for_update(*args, **kwargs)

    monkeypatch.setattr(domain.StaffEnrollment.objects, "select_for_update", disable_before_lock)
    response = post(browser, "auth/step-up", {"code": pyotp.TOTP(operator.secret).at(clock.now)})
    assert_problem(response, 401, "admin_auth_required")
    assert browser.cookies[auth.STAFF_COOKIE].value == previous


def test_owner_lock_excludes_a_competing_database_transaction():
    """A second connection cannot enter the Owner critical section concurrently.

    The shared fixture keeps data uncommitted and rolls back audit-trigger writes;
    use only the advisory lock on the independent connection, never commit fixture
    records to make them visible to another thread.
    """
    with transaction.atomic(), policy.owner_lock():
        with psycopg.connect(**connection.get_connection_params()) as contender:
            with contender.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [policy.OWNER_LOCK_ID])
                assert cursor.fetchone() == (False,)
            contender.rollback()


def test_two_enrolled_owners_can_lose_access_only_until_one_remains(operator):
    other = get_user_model().objects.create_user(
        username=f"other-owner-{uuid4()}",
        password=PASSWORD,
        is_staff=True,
    )
    other.groups.add(Group.objects.get(name=f"{policy.GROUP_PREFIX}Owner"))
    remaining = domain.StaffEnrollment.objects.create(
        user=other,
        mfa_secret_encrypted=views.encrypt(pyotp.random_base32()),
    )
    with transaction.atomic(), policy.owner_lock():
        policy.ensure_not_last_owner(operator.enrollment)
        domain.StaffEnrollment.objects.filter(pk=operator.enrollment.pk).update(enabled=False)
    with transaction.atomic(), policy.owner_lock():
        with pytest.raises(TaskillerAPIError) as error:
            policy.ensure_not_last_owner(remaining)
    assert error.value.code == "admin_last_owner"


def test_bootstrap_command_creates_audited_single_use_owner_invitation(browser, clock):
    user = get_user_model().objects.create_user(
        username=f"bootstrap-{uuid4()}",
        password=PASSWORD,
        is_staff=True,
    )
    output = StringIO()
    call_command(
        "bootstrap_staff_console",
        username=user.username,
        reason="CI operator enrollment",
        stdout=output,
    )
    token = output.getvalue().strip().splitlines()[-1]
    enrollment = domain.StaffEnrollment.objects.get(user=user)
    invitation = domain.StaffChallenge.objects.get(enrollment=enrollment, purpose="enrollment")
    assert invitation.secret_digest == auth.digest(token)
    assert enrollment.enabled and not enrollment.mfa_secret_encrypted
    assert user.groups.filter(name=f"{policy.GROUP_PREFIX}Owner").exists()
    event = domain.AdminAuditRecord.objects.get(
        action="operator.bootstrap_owner", target_id=str(enrollment.id)
    )
    assert event.actor_id is None and event.reason_code == "operator_cli"
    assert token not in str(event.changes_json)
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")
    response = post(browser, "auth/enroll", {"invitationToken": token, "password": PASSWORD})
    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.consumed_at is not None


def test_cli_recovery_requires_explicit_flag_and_revokes_all_factors(browser, operator, clock):
    complete_login(browser, operator, clock)
    session = session_for(browser)
    recovery = domain.StaffRecoveryCode.objects.create(
        enrollment=operator.enrollment,
        code_digest=auth.digest("unused-recovery"),
    )
    pending, _token = views.challenge(operator.enrollment, "login")
    with pytest.raises(CommandError, match="Already enrolled"):
        call_command(
            "bootstrap_staff_console",
            username=operator.user.username,
            reason="CI recovery",
            stdout=StringIO(),
        )
    output = StringIO()
    call_command(
        "bootstrap_staff_console",
        username=operator.user.username,
        recover_mfa=True,
        reason="CI lost MFA recovery",
        stdout=output,
    )
    operator.enrollment.refresh_from_db()
    session.refresh_from_db()
    pending.refresh_from_db()
    recovery.refresh_from_db()
    assert not operator.enrollment.mfa_secret_encrypted
    assert operator.enrollment.last_totp_step == -1
    assert operator.enrollment.version > 1
    assert session.revoked_at and pending.consumed_at and recovery.used_at
    assert domain.AdminAuditRecord.objects.filter(
        action="operator.mfa_recovery",
        target_id=str(operator.enrollment.id),
    ).exists()
    assert_problem(browser.get(BASE + "me"), 401, "admin_auth_required")


def test_pending_enrollment_is_invalidated_by_password_reset(browser, operator, clock):
    domain.StaffEnrollment.objects.filter(pk=operator.enrollment.id).update(mfa_secret_encrypted="")
    _, token = views.challenge(operator.enrollment, "enrollment")
    started = post(browser, "auth/enroll", {"invitationToken": token, "password": PASSWORD})
    assert started.status_code == 200
    operator.user.set_password("Changed-operator-password-after-enrollment!")
    operator.user.save(update_fields=["password"])
    response = post(
        browser,
        "auth/enroll/confirm",
        {
            "challengeId": str(started.data["challengeId"]),
            "code": pyotp.TOTP(started.data["secret"]).at(clock.now),
        },
    )
    assert_problem(response, 401, "admin_mfa_invalid")
    operator.enrollment.refresh_from_db()
    assert not operator.enrollment.mfa_secret_encrypted
