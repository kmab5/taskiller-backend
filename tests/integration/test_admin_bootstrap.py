# ruff: noqa: E402
from __future__ import annotations

import os
from io import StringIO

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.integration


def test_bootstrap_creates_authenticatable_admin_and_updates_same_account(monkeypatch):
    monkeypatch.setenv("TASKILLER_ADMIN_USERNAME", "bootstrap-test-owner")
    monkeypatch.setenv("TASKILLER_ADMIN_EMAIL", "bootstrap-owner@example.test")
    monkeypatch.setenv("TASKILLER_ADMIN_PASSWORD", "first-test-bootstrap-password")
    call_command("bootstrap_taskiller_admin", stdout=StringIO())
    User = get_user_model()
    user = User.objects.get(username="bootstrap-test-owner")
    assert user.email == "bootstrap-owner@example.test"
    assert user.is_active and user.is_staff and user.is_superuser
    assert authenticate(username=user.username, password="first-test-bootstrap-password") == user
    original_hash = user.password
    call_command("bootstrap_taskiller_admin", if_configured=True, stdout=StringIO())
    user.refresh_from_db()
    assert user.password == original_hash
    monkeypatch.setenv("TASKILLER_ADMIN_PASSWORD", "second-test-bootstrap-password")
    call_command("bootstrap_taskiller_admin", stdout=StringIO())
    assert User.objects.filter(username=user.username).count() == 1
    assert authenticate(username=user.username, password="second-test-bootstrap-password") == user
    assert authenticate(username=user.username, password="first-test-bootstrap-password") is None
    monkeypatch.delenv("TASKILLER_ADMIN_PASSWORD")
    call_command("bootstrap_taskiller_admin", if_configured=True, stdout=StringIO())
    assert authenticate(username=user.username, password="second-test-bootstrap-password") == user
