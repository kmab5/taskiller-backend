# ruff: noqa: E402
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.contrib import admin

from taskiller.django_domain import models as domain


def test_all_existing_domain_models_are_django_managed() -> None:
    models = [
        model
        for model in domain.ExistingTaskillerModel.__subclasses__()
        if not model._meta.abstract
    ]

    assert models
    assert all(model._meta.managed is True for model in models)


def test_composite_primary_keys_match_existing_tables() -> None:
    assert [field.column for field in domain.IdempotencyRecord._meta.pk_fields] == [
        "owner_id",
        "scope",
        "idempotency_key",
    ]
    assert [field.column for field in domain.RateLimitBucket._meta.pk_fields] == [
        "scope",
        "subject_hash",
    ]


def test_operational_models_are_registered_read_only() -> None:
    assert domain.TaskillerUser in admin.site._registry
    assert domain.ExecutionSession in admin.site._registry

    for model in (
        domain.RefreshToken,
        domain.EmailVerificationToken,
        domain.PasswordResetToken,
        domain.IdempotencyRecord,
        domain.RateLimitBucket,
        domain.WorkType,
        domain.WorkItem,
        domain.FocusPlan,
        domain.StaffEnrollment,
        domain.StaffChallenge,
        domain.StaffSession,
        domain.StaffRecoveryCode,
    ):
        assert model not in admin.site._registry

    forbidden_fields = {
        "password_hash",
        "token_hash",
        "description",
        "notes",
        "note",
        "payload_json",
        "metadata_json",
        "archive_bytes",
        "last_error",
        "mfa_secret_encrypted",
        "token_digest",
        "auth_hash",
        "secret_digest",
        "code_digest",
        "suspension_reason",
    }
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label != "django_domain":
            continue
        assert model_admin.fields
        assert not forbidden_fields.intersection(model_admin.fields)
        assert model_admin.get_readonly_fields(None) == model_admin.fields
        assert not model_admin.has_add_permission(None)
        assert not model_admin.has_change_permission(None)
        assert not model_admin.has_delete_permission(None)
