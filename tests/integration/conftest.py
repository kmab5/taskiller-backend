"""Transactional integration tests against an explicitly selected test database."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()


@pytest.fixture(autouse=True)
def integration_transaction(integration_database):
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        yield
        transaction.set_rollback(True)
