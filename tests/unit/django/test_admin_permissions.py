# ruff: noqa: E402
"""Central staff policy tests without a database or Django superuser shortcuts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest
from cryptography.fernet import Fernet
from django.test import override_settings

from taskiller.django_api.admin_api import permissions as policy
from taskiller.django_api.errors import TaskillerAPIError

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_console(monkeypatch):
    for name in ("USERNAME", "EMAIL", "PASSWORD"):
        monkeypatch.delenv(f"TASKILLER_ADMIN_{name}", raising=False)
    monkeypatch.setattr(policy, "utc_now", lambda: NOW)
    with override_settings(
        SECRET_KEY="isolated-staff-policy-test-secret",
        ADMIN_CONSOLE_ENABLED=True,
        ADMIN_CONSOLE_WRITES_ENABLED=True,
        ADMIN_CONSOLE_ORIGINS=["https://console.example.test"],
        ADMIN_CONSOLE_ENCRYPTION_KEYS=[Fernet.generate_key().decode()],
        ADMIN_CONSOLE_COOKIE_SECURE=True,
    ):
        yield


@pytest.fixture
def context(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, is_active=True, is_staff=True)
    enrollment = SimpleNamespace(id=uuid4(), user=user, enabled=True)
    session = SimpleNamespace(
        enrollment_id=enrollment.id,
        revoked_at=None,
        expires_at=NOW + timedelta(hours=1),
        mfa_verified_at=NOW,
    )
    queryset = Mock()
    queryset.filter.return_value.first.return_value = enrollment
    monkeypatch.setattr(
        policy.StaffEnrollment.objects, "select_related", Mock(return_value=queryset)
    )
    monkeypatch.setattr(policy, "effective_capabilities", Mock(return_value=["view_users"]))
    return SimpleNamespace(request=SimpleNamespace(user=user, auth=session), enrollment=enrollment)


def test_roles_have_exact_initial_capabilities():
    assert policy.GROUP_PREFIX == "taskiller-console:"
    assert policy.ROLE_CAPABILITIES["Owner"] == policy.CAPABILITIES
    assert policy.ROLE_CAPABILITIES["Administrator"] == policy.CAPABILITIES - {
        "manage_staff",
        "read_private",
        "manage_privacy",
    }
    assert policy.ROLE_CAPABILITIES["Support"] == {
        "view_users",
        "view_activity",
        "recovery_email",
    }
    assert policy.ROLE_CAPABILITIES["Analyst"] == {"view_overview"}


def test_superuser_has_no_implicit_console_capabilities(monkeypatch):
    group_query = Mock()
    group_query.values_list.return_value = []
    group_filter = Mock(return_value=group_query)
    monkeypatch.setattr(policy.Permission.objects, "filter", group_filter)
    direct = Mock()
    direct.filter.return_value.values_list.return_value = []
    user = SimpleNamespace(
        is_superuser=True,
        is_staff=True,
        user_permissions=direct,
        has_perm=Mock(side_effect=AssertionError("superuser permission shortcut")),
        get_all_permissions=Mock(side_effect=AssertionError("implicit permission shortcut")),
    )
    assert policy.effective_capabilities(user) == []
    user.has_perm.assert_not_called()
    user.get_all_permissions.assert_not_called()
    filters = group_filter.call_args.kwargs
    assert filters["group__name__startswith"] == policy.GROUP_PREFIX
    assert filters["content_type__model"] == "staffenrollment"
    assert filters["content_type__app_label"] == "django_domain"
    assert set(direct.filter.call_args.kwargs["codename__in"]) == {
        "console_read_private",
        "console_manage_privacy",
    }


def test_effective_capabilities_are_allowlisted_unique_and_sorted(monkeypatch):
    group_query = Mock()
    group_query.values_list.return_value = [
        "console_view_users",
        "console_view_users",
        "console_unknown",
        "change_user",
    ]
    monkeypatch.setattr(policy.Permission.objects, "filter", Mock(return_value=group_query))
    direct = Mock()
    direct.filter.return_value.values_list.return_value = ["console_read_private"]
    user = SimpleNamespace(user_permissions=direct)
    assert policy.effective_capabilities(user) == ["read_private", "view_users"]


def test_allowed_capability_rechecks_current_enrollment(context):
    assert policy.require_capability(context.request, "view_users") is context.enrollment
    policy.StaffEnrollment.objects.select_related.return_value.filter.assert_called_once_with(
        id=context.enrollment.id,
        enabled=True,
        user__is_active=True,
        user__is_staff=True,
    )


@pytest.mark.parametrize("capability", ["manage_staff", "read_private", "made_up_action"])
def test_missing_or_unknown_capability_is_denied(context, capability):
    with pytest.raises(TaskillerAPIError) as error:
        policy.require_capability(context.request, capability)
    assert error.value.status_code == 403
    assert error.value.code == "admin_permission_denied"


@pytest.mark.parametrize(
    "failure", ["anonymous", "missing-session", "removed-enrollment", "revoked", "expired"]
)
def test_invalid_identity_or_session_is_unauthorized(context, failure):
    request = context.request
    if failure == "anonymous":
        request.user.is_authenticated = False
    elif failure == "missing-session":
        request.auth = None
    elif failure == "removed-enrollment":
        queryset = policy.StaffEnrollment.objects.select_related.return_value
        queryset.filter.return_value.first.return_value = None
    elif failure == "revoked":
        request.auth.revoked_at = NOW
    else:
        request.auth.expires_at = NOW
    with pytest.raises(TaskillerAPIError) as error:
        policy.require_capability(request, "view_users")
    assert error.value.status_code == 401


@pytest.mark.parametrize("age,allowed", [(299, True), (300, True), (301, False)])
def test_step_up_freshness_boundary(context, age, allowed):
    context.request.auth.mfa_verified_at = NOW - timedelta(seconds=age)
    if allowed:
        assert policy.require_capability(context.request, "view_users", step_up=True)
    else:
        with pytest.raises(TaskillerAPIError) as error:
            policy.require_capability(context.request, "view_users", step_up=True)
        assert error.value.code == "admin_step_up_required"


def test_old_mfa_does_not_block_non_step_up_reads(context):
    context.request.auth.mfa_verified_at = NOW - timedelta(hours=1)
    assert policy.require_capability(context.request, "view_users")


def test_step_up_never_substitutes_for_capability(context):
    with pytest.raises(TaskillerAPIError) as error:
        policy.require_capability(context.request, "manage_staff", step_up=True)
    assert error.value.code == "admin_permission_denied"


@pytest.mark.parametrize(
    "is_owner,count,denied", [(True, 1, True), (True, 2, False), (False, 1, False)]
)
def test_last_owner_protection(context, monkeypatch, is_owner, count, denied):
    owners = Mock()
    owners.filter.return_value.exists.return_value = is_owner
    owners.count.return_value = count
    manager = Mock()
    manager.return_value.exclude.return_value.distinct.return_value = owners
    monkeypatch.setattr(policy.StaffEnrollment.objects, "filter", manager)
    if denied:
        with pytest.raises(TaskillerAPIError) as error:
            policy.ensure_not_last_owner(context.enrollment)
        assert error.value.code == "admin_last_owner"
    else:
        policy.ensure_not_last_owner(context.enrollment)
    assert manager.call_args.kwargs["user__groups__name"] == "taskiller-console:Owner"
    manager.return_value.exclude.assert_called_once_with(mfa_secret_encrypted="")


def test_owner_lock_uses_shared_transaction_scoped_advisory_lock(monkeypatch):
    cursor = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=cursor)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(policy, "connection", SimpleNamespace(cursor=lambda: manager))
    with policy.owner_lock():
        cursor.execute.assert_called_once_with(
            "SELECT pg_advisory_xact_lock(%s)",
            [policy.OWNER_LOCK_ID],
        )
