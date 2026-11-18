"""Require an explicit disposable database for every integration-marked test."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest


@pytest.fixture(scope="session")
def integration_database():
    url = os.environ.get("TASKILLER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("TASKILLER_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Integration tests require a disposable local PostgreSQL database")
    if os.environ.get("TASKILLER_ENV") != "test":
        pytest.fail("Integration tests require TASKILLER_ENV=test")
    if os.environ.get("TASKILLER_DATABASE_URL") != url:
        pytest.fail("TASKILLER_DATABASE_URL must match TASKILLER_TEST_DATABASE_URL")

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)


@pytest.fixture(autouse=True)
def guard_integration_database(request):
    if request.node.get_closest_marker("integration") is not None:
        request.getfixturevalue("integration_database")
