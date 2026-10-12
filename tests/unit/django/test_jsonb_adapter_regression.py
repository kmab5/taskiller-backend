"""JSONB adapter regression: psycopg can return decoded Python JSON values."""

# ruff: noqa: E402
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "taskiller.django_project.settings",
)

import django

django.setup()

from taskiller.django_domain import models as domain


@pytest.mark.parametrize(
    "value",
    [
        {"segments": [{"kind": "work", "seconds": 1500}]},
        ["work", "break"],
        42,
        1.5,
        True,
        False,
        None,
    ],
)
def test_jsonb_field_accepts_already_decoded_driver_values(value):
    field = domain.PsycopgCompatibleJSONField()
    assert field.from_db_value(value, None, None) == value


@pytest.mark.parametrize(
    "value", [{"segments": [{"kind": "work"}]}, ["work", "break"], 42, True, "hello"]
)
def test_jsonb_field_still_decodes_json_text(value):
    field = domain.PsycopgCompatibleJSONField()
    assert field.from_db_value(json.dumps(value), None, None) == value


def test_jsonb_decoder_is_used_by_all_domain_json_fields():
    for model in (
        domain.IdempotencyRecord,
        domain.FocusPlanRecommendation,
        domain.ExecutionSession,
        domain.SessionEvent,
        domain.OutboxJob,
        domain.SecurityEvent,
    ):
        for field in model._meta.fields:
            if field.get_internal_type() == "JSONField":
                assert isinstance(field, domain.PsycopgCompatibleJSONField), (
                    model.__name__,
                    field.name,
                )


def test_decoder_only_change_does_not_create_database_migration():
    assert domain.ExecutionSession._meta.get_field("plan_snapshot_json").deconstruct()[1] == (
        "django.db.models.JSONField"
    )
