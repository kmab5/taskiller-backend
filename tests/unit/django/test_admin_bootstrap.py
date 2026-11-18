# ruff: noqa: E402
from __future__ import annotations

import os
from io import StringIO
from unittest.mock import Mock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.fixture(autouse=True)
def clean_admin_environment(monkeypatch):
    for name in ("USERNAME", "EMAIL", "PASSWORD"):
        monkeypatch.delenv(f"TASKILLER_ADMIN_{name}", raising=False)


def configured(monkeypatch):
    monkeypatch.setenv("TASKILLER_ADMIN_USERNAME", "site-owner")
    monkeypatch.setenv("TASKILLER_ADMIN_EMAIL", " Owner@Example.Test ")
    monkeypatch.setenv("TASKILLER_ADMIN_PASSWORD", "test-bootstrap-password")


def test_bootstrap_uses_separate_username_and_email(monkeypatch):
    configured(monkeypatch)
    User = get_user_model()
    user = User(username="site-owner")
    user.save = Mock()
    create = Mock(return_value=(user, True))
    monkeypatch.setattr(User.objects, "get_or_create", create)
    output = StringIO()
    call_command("bootstrap_taskiller_admin", stdout=output)
    assert create.call_args.kwargs["username"] == "site-owner"
    assert user.email == "owner@example.test"
    assert user.is_staff and user.is_superuser and user.is_active
    assert user.check_password("test-bootstrap-password")
    assert "test-bootstrap-password" not in output.getvalue()
    user.save.assert_called_once()


def test_bootstrap_retains_email_login_without_username(monkeypatch):
    configured(monkeypatch)
    monkeypatch.delenv("TASKILLER_ADMIN_USERNAME")
    User = get_user_model()
    user = User()
    user.save = Mock()
    create = Mock(return_value=(user, True))
    monkeypatch.setattr(User.objects, "get_or_create", create)
    call_command("bootstrap_taskiller_admin", stdout=StringIO())
    assert create.call_args.kwargs["username"] == "owner@example.test"


def test_optional_bootstrap_without_password_does_not_touch_database(monkeypatch):
    monkeypatch.setenv("TASKILLER_ADMIN_USERNAME", "site-owner")
    monkeypatch.setenv("TASKILLER_ADMIN_EMAIL", "owner@example.test")
    create = Mock(side_effect=AssertionError("unexpected database access"))
    monkeypatch.setattr(get_user_model().objects, "get_or_create", create)
    call_command("bootstrap_taskiller_admin", if_configured=True, stdout=StringIO())
    create.assert_not_called()


@pytest.mark.parametrize("missing", ["EMAIL", "PASSWORD"])
def test_explicit_bootstrap_rejects_missing_credentials(monkeypatch, missing):
    configured(monkeypatch)
    monkeypatch.delenv(f"TASKILLER_ADMIN_{missing}")
    with pytest.raises(CommandError, match=f"TASKILLER_ADMIN_{missing}"):
        call_command("bootstrap_taskiller_admin", stdout=StringIO())
