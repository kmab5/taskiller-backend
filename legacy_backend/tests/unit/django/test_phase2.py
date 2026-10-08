from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.contrib import admin

from taskiller.django_domain import models as domain


def test_all_existing_domain_models_are_unmanaged() -> None:
    models = [
        model
        for model in domain.ExistingTaskillerModel.__subclasses__()
        if not model._meta.abstract
    ]

    assert models
    assert all(model._meta.managed is False for model in models)


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
    assert domain.WorkItem in admin.site._registry
    assert domain.ExecutionSession in admin.site._registry

    for model in (
        domain.RefreshToken,
        domain.EmailVerificationToken,
        domain.PasswordResetToken,
        domain.IdempotencyRecord,
        domain.RateLimitBucket,
    ):
        assert model not in admin.site._registry
