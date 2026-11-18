# ruff: noqa: E402
import os
from unittest.mock import Mock
from uuid import UUID, uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from taskiller.core.config import Settings
from taskiller.django_api import auth_service, middleware
from taskiller.django_api.errors import TaskillerAPIError


@pytest.mark.parametrize("endpoint", ["login", "register", "refresh", "logout", "logout-all"])
@pytest.mark.parametrize(
    "headers",
    [
        {"HTTP_ORIGIN": "https://evil.example"},
        {"HTTP_ORIGIN": "null"},
        {"HTTP_SEC_FETCH_SITE": "cross-site"},
    ],
)
def test_reject_cross_site_auth(monkeypatch, endpoint, headers):
    monkeypatch.setattr(middleware, "get_settings", lambda: Settings(_env_file=None))
    handler = Mock(return_value=HttpResponse(status=200))
    response = middleware.TaskillerRuntimeMiddleware(handler)(
        RequestFactory().post(f"/api/v1/auth/{endpoint}", **headers)
    )
    assert response.status_code == 403
    handler.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"HTTP_ORIGIN": "http://localhost:3000"}])
def test_allow_trusted_or_native_auth(monkeypatch, headers):
    monkeypatch.setattr(middleware, "get_settings", lambda: Settings(_env_file=None))
    response = middleware.TaskillerRuntimeMiddleware(lambda r: HttpResponse(status=200))(
        RequestFactory().post("/api/v1/auth/login", **headers)
    )
    assert response.status_code == 200


def test_invalid_reset_does_not_hash(monkeypatch):
    monkeypatch.setattr(auth_service, "taskiller_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(
        auth_service.PasswordResetToken.objects, "filter", lambda **kw: Mock(first=lambda: None)
    )
    hasher = Mock()
    monkeypatch.setattr(auth_service, "password_hasher", hasher)
    with pytest.raises(TaskillerAPIError):
        auth_service.DjangoAuthService().confirm_password_reset("invalid", "new-password")
    hasher.hash.assert_not_called()


def test_durable_token_is_domain_separated():
    from taskiller.auth.security import derive_auth_email_token

    settings = Settings(_env_file=None)
    token_id = uuid4()
    token = derive_auth_email_token(token_id, "password_reset", settings)
    assert token == derive_auth_email_token(token_id, "password_reset", settings)
    assert token != derive_auth_email_token(token_id, "email_verification", settings)
    assert token != derive_auth_email_token(uuid4(), "password_reset", settings)
    assert token != derive_auth_email_token(
        token_id,
        "password_reset",
        settings.model_copy(update={"token_hash_secret": "other-secret"}),
    )


@pytest.mark.parametrize(
    "body", [b"", b"{}", b'{"Messages":[{}]}', b'{"Messages":[{"Status":"error"}]}']
)
def test_mailjet_requires_explicit_acceptance(monkeypatch, body):
    import urllib.request

    from taskiller.auth.email import MailjetEmailSender

    response = Mock(status=200, read=lambda: body)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
    sender = MailjetEmailSender(
        Settings(
            _env_file=None,
            mailjet_api_key="test",
            mailjet_secret_key="test",
            mailjet_from_email="test@example.com",
        )
    )
    with pytest.raises(RuntimeError):
        sender._send_sync(
            recipient="user@example.com", subject="test", text="test", html_body="test"
        )


def test_registration_has_independent_ip_budget(monkeypatch):
    from rest_framework.test import APIRequestFactory

    from taskiller.django_api import views

    monkeypatch.setattr(
        views,
        "_auth_service",
        lambda: Mock(
            register=Mock(side_effect=AssertionError("registration must be throttled first"))
        ),
    )
    calls = []

    def limit(request, **kwargs):
        calls.append(kwargs)
        if kwargs["scope"] == "auth_register_ip":
            raise TaskillerAPIError(429, "rate_limit_exceeded", "Too many requests")

    monkeypatch.setattr(views, "enforce_rate_limit", limit)
    response = views.RegisterView.as_view()(
        APIRequestFactory().post(
            "/api/v1/auth/register",
            {"email": "first@example.com", "password": "very-secure-password-123"},
            format="json",
        )
    )
    assert response.status_code == 429
    assert calls[0]["subject"] == "127.0.0.1|"


def test_limits_are_configurable():
    settings = Settings(_env_file=None, auth_email_cooldown_seconds=123)
    assert settings.auth_email_cooldown_seconds == 123
    assert settings.auth_confirm_limit > 0
    assert settings.auth_email_recipient_limit > 0


def test_queue_contains_only_references(monkeypatch):
    from datetime import timedelta

    from taskiller.auth.security import derive_auth_email_token, hash_opaque_token
    from taskiller.core.time import utc_now

    settings = Settings(_env_file=None)
    monkeypatch.setattr(auth_service, "taskiller_settings", lambda: settings)
    token_rows, jobs = [], []
    monkeypatch.setattr(
        auth_service.PasswordResetToken.objects, "create", lambda **kw: token_rows.append(kw)
    )
    monkeypatch.setattr(auth_service.OutboxJob.objects, "create", lambda **kw: jobs.append(kw))
    user = Mock(id=uuid4())
    now = utc_now()
    auth_service.DjangoAuthService()._queue_auth_email(user, "password_reset", now)
    payload = jobs[0]["payload_json"]
    assert set(payload) == {"tokenId", "userId", "kind"}
    assert jobs[0]["job_type"] == "auth_email"
    row = token_rows[0]
    assert row["token_hash"] == hash_opaque_token(
        derive_auth_email_token(row["id"], "password_reset", settings), settings
    )
    assert row["expires_at"] == now + timedelta(minutes=settings.password_reset_ttl_minutes)


@pytest.mark.parametrize("state", ["valid", "consumed", "expired", "inactive"])
def test_delivery_reconstructs_token_and_skips_stale(monkeypatch, state):
    from datetime import timedelta

    from taskiller.auth.email import MemoryEmailSender
    from taskiller.auth.security import derive_auth_email_token, hash_opaque_token
    from taskiller.core.time import utc_now
    from taskiller.django_operations import email_delivery

    settings = Settings(_env_file=None)
    token_id, user_id = uuid4(), uuid4()
    plain = derive_auth_email_token(token_id, "password_reset", settings)
    row = Mock(
        consumed_at=utc_now() if state == "consumed" else None,
        expires_at=utc_now() + timedelta(minutes=-1 if state == "expired" else 10),
        token_hash=hash_opaque_token(plain, settings),
    )
    user = None if state == "inactive" else Mock(email="user@example.com")
    monkeypatch.setattr(
        email_delivery.PasswordResetToken.objects, "filter", lambda **kw: Mock(first=lambda: row)
    )
    monkeypatch.setattr(
        email_delivery.TaskillerUser.objects, "filter", lambda **kw: Mock(first=lambda: user)
    )
    sender = MemoryEmailSender()
    monkeypatch.setattr(email_delivery, "auth_email_sender", lambda: sender)
    monkeypatch.setattr(email_delivery, "taskiller_settings", lambda: settings)
    email_delivery.deliver_auth_email(
        {"tokenId": str(token_id), "userId": str(user_id), "kind": "password_reset"}
    )
    assert sender.reset_tokens == ({"user@example.com": plain} if state == "valid" else {})


def test_preflight_is_handled_before_auth_origin_policy(monkeypatch):
    monkeypatch.setattr(middleware, "get_settings", lambda: Settings(_env_file=None))
    handler = Mock(return_value=HttpResponse(status=200))
    response = middleware.TaskillerRuntimeMiddleware(handler)(
        RequestFactory().options("/api/v1/auth/login", HTTP_ORIGIN="http://localhost:3000")
    )
    assert response.status_code == 204
    assert response["Access-Control-Allow-Origin"] == "http://localhost:3000"
    handler.assert_not_called()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    from taskiller.django_api import runtime

    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: Settings(_env_file=None, jwt_secret="test-secret-with-at-least-32-characters"),
    )
    runtime.taskiller_settings.cache_clear()
    yield
    runtime.taskiller_settings.cache_clear()


@pytest.mark.integration
def test_durable_email_round_trip_and_sibling_consumption(monkeypatch):
    if not os.environ.get("TASKILLER_TEST_DATABASE_URL"):
        pytest.skip("Requires explicit disposable database URL")
    from datetime import timedelta

    from django.db import transaction

    from taskiller.auth.email import MemoryEmailSender
    from taskiller.auth.security import derive_auth_email_token
    from taskiller.core.time import utc_now
    from taskiller.django_domain.models import OutboxJob, PasswordResetToken
    from taskiller.django_operations import email_delivery

    sender = MemoryEmailSender()
    monkeypatch.setattr(email_delivery, "auth_email_sender", lambda: sender)
    with transaction.atomic():
        service = auth_service.DjangoAuthService()
        user = service.register(
            {"email": f"{uuid4()}@example.com", "password": "test-password-123"}, None
        ).user
        service.request_password_reset(user.email)
        jobs = OutboxJob.objects.filter(job_type="auth_email", payload_json__userId=str(user.id))
        assert jobs.count() == 1
        first = jobs.get()
        service.request_password_reset(user.email)
        assert jobs.count() == 1
        PasswordResetToken.objects.filter(user_id=user.id).update(
            created_at=utc_now() - timedelta(minutes=2)
        )
        service.request_password_reset(user.email)
        assert jobs.count() == 2
        assert (
            PasswordResetToken.objects.filter(user_id=user.id, consumed_at__isnull=True).count()
            == 2
        )
        email_delivery.deliver_auth_email(first.payload_json)
        plain = sender.reset_tokens[user.email]
        assert plain == derive_auth_email_token(
            UUID(first.payload_json["tokenId"]), "password_reset", service.settings
        )
        service.confirm_password_reset(plain, "replacement-password-123")
        assert not PasswordResetToken.objects.filter(
            user_id=user.id, consumed_at__isnull=True
        ).exists()
        sender.reset_tokens.clear()
        for job in jobs:
            email_delivery.deliver_auth_email(job.payload_json)
        assert not sender.reset_tokens
        transaction.set_rollback(True)


@pytest.mark.integration
def test_enqueue_failure_rolls_back_token(monkeypatch):
    if not os.environ.get("TASKILLER_TEST_DATABASE_URL"):
        pytest.skip("Requires explicit disposable database URL")
    from django.db import transaction

    from taskiller.django_domain.models import PasswordResetToken

    with transaction.atomic():
        service = auth_service.DjangoAuthService()
        user = service.register(
            {"email": f"{uuid4()}@example.com", "password": "test-password-123"}, None
        ).user

        def fail(**kwargs):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(auth_service.OutboxJob.objects, "create", fail)
        with pytest.raises(RuntimeError, match="queue unavailable"):
            service.request_password_reset(user.email)
        assert not PasswordResetToken.objects.filter(user_id=user.id).exists()
        transaction.set_rollback(True)


@pytest.mark.parametrize("view_name", ["ConfirmPasswordResetView", "ConfirmEmailVerificationView"])
def test_confirmation_throttle_precedes_validation(monkeypatch, view_name):
    from rest_framework.test import APIRequestFactory

    from taskiller.django_api import views

    def reject(request, **kwargs):
        raise TaskillerAPIError(429, "rate_limit_exceeded", "Too many attempts")

    monkeypatch.setattr(views, "enforce_rate_limit", reject)
    response = getattr(views, view_name).as_view()(
        APIRequestFactory().post("/auth/confirm", {}, format="json")
    )
    assert response.status_code == 429


@pytest.mark.integration
def test_verification_cooldown_and_older_token_remains_valid(monkeypatch):
    if not os.environ.get("TASKILLER_TEST_DATABASE_URL"):
        pytest.skip("Requires explicit disposable database URL")
    from datetime import timedelta

    from django.db import transaction

    from taskiller.auth.security import derive_auth_email_token
    from taskiller.core.time import utc_now
    from taskiller.django_domain.models import EmailVerificationToken

    with transaction.atomic():
        service = auth_service.DjangoAuthService()
        user = service.register(
            {"email": f"{uuid4()}@example.com", "password": "test-password-123"}, None
        ).user
        service.request_email_verification(user)
        first = EmailVerificationToken.objects.get(user_id=user.id)
        service.request_email_verification(user)
        assert EmailVerificationToken.objects.filter(user_id=user.id).count() == 1
        EmailVerificationToken.objects.filter(user_id=user.id).update(
            created_at=utc_now() - timedelta(minutes=2)
        )
        service.request_email_verification(user)
        plain = derive_auth_email_token(first.id, "email_verification", service.settings)
        service.confirm_email_verification(plain)
        user.refresh_from_db()
        assert user.email_verified_at is not None
        assert not EmailVerificationToken.objects.filter(
            user_id=user.id, consumed_at__isnull=True
        ).exists()
        transaction.set_rollback(True)


def test_completion_log_omits_credentials(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(middleware, "get_settings", lambda: Settings(_env_file=None))
    with caplog.at_level(logging.INFO, logger=middleware.__name__):
        middleware.TaskillerRuntimeMiddleware(lambda r: HttpResponse(status=200))(
            RequestFactory().get(
                "/api/v1/exports/file?token=secret",
                HTTP_AUTHORIZATION="Bearer secret",
                HTTP_COOKIE="secret",
            )
        )
    record = caplog.records[-1]
    assert record.path == "/api/v1/exports/file"
    assert record.status == 200
    assert record.duration_ms >= 0
    assert "secret" not in str(record.__dict__)
    assert not hasattr(record, "method")
    assert not hasattr(record, "request_id")


@pytest.mark.integration
def test_requested_email_is_claimed_and_processed_by_worker(monkeypatch):
    if not os.environ.get("TASKILLER_TEST_DATABASE_URL"):
        pytest.skip("Requires explicit disposable database URL")
    from datetime import UTC, datetime

    from django.db import transaction

    from taskiller.auth.email import MemoryEmailSender
    from taskiller.django_domain.models import (
        AuthSession,
        EmailVerificationToken,
        OutboxJob,
        PasswordResetToken,
        RefreshToken,
        TaskillerUser,
        UserPreferences,
    )
    from taskiller.django_operations import email_delivery, worker_service

    sender = MemoryEmailSender()
    monkeypatch.setattr(email_delivery, "auth_email_sender", lambda: sender)
    service = auth_service.DjangoAuthService()
    user = service.register(
        {"email": f"{uuid4()}@example.com", "password": "test-password-123"}, None
    ).user
    try:
        service.request_password_reset(user.email)
        job = OutboxJob.objects.get(job_type="auth_email", payload_json__userId=str(user.id))
        assert job.status == "queued"
        # Prioritize only this test's job without modifying other contributors' jobs.
        OutboxJob.objects.filter(id=job.id).update(available_at=datetime(1, 1, 1, tzinfo=UTC))
        claim = worker_service.claim_job("auth-hardening-test", with_token=True)
        assert claim is not None
        job_id, claim_token = claim
        assert job_id == job.id
        assert worker_service.process_job(job_id, claim_token=claim_token)
        job.refresh_from_db()
        assert job.status == "succeeded"
        assert user.email in sender.reset_tokens
        service.confirm_password_reset(sender.reset_tokens[user.email], "replacement-password-123")
    finally:
        with transaction.atomic():
            OutboxJob.objects.filter(payload_json__userId=str(user.id)).delete()
            PasswordResetToken.objects.filter(user_id=user.id).delete()
            EmailVerificationToken.objects.filter(user_id=user.id).delete()
            RefreshToken.objects.filter(session__user_id=user.id).delete()
            AuthSession.objects.filter(user_id=user.id).delete()
            UserPreferences.objects.filter(user_id=user.id).delete()
            TaskillerUser.objects.filter(id=user.id).delete()
