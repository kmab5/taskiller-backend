"""Validate Django's unmanaged bridge against the live Alembic-owned schema."""

from __future__ import annotations

import os
from collections.abc import Iterable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.db import connection  # noqa: E402

from taskiller.django_domain.models import (  # noqa: E402
    AccountDeletionRequest,
    AuthSession,
    DataExportRequest,
    EmailVerificationToken,
    ExecutionSession,
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
    IdempotencyRecord,
    OutboxJob,
    PasswordResetToken,
    RateLimitBucket,
    RefreshToken,
    SecurityEvent,
    SessionEvent,
    SessionReview,
    TaskillerUser,
    UserPreferences,
    WorkItem,
    WorkType,
)

DOMAIN_MODELS = (
    TaskillerUser,
    UserPreferences,
    AuthSession,
    RefreshToken,
    EmailVerificationToken,
    PasswordResetToken,
    IdempotencyRecord,
    WorkType,
    WorkItem,
    FocusPlanRecommendation,
    FocusPlan,
    FocusPlanSegment,
    ExecutionSession,
    SessionEvent,
    SessionReview,
    DataExportRequest,
    AccountDeletionRequest,
    OutboxJob,
    RateLimitBucket,
    SecurityEvent,
)


def _columns(model: type[object]) -> set[str]:
    return {
        field.column
        for field in model._meta.local_fields  # type: ignore[attr-defined]
        if field.column is not None
    }


def _pk_columns(model: type[object]) -> tuple[str, ...]:
    return tuple(
        field.column
        for field in model._meta.pk_fields  # type: ignore[attr-defined]
        if field.column is not None
    )


def _primary_key_columns(constraints: dict[str, dict[str, object]]) -> tuple[str, ...]:
    for constraint in constraints.values():
        if constraint.get("primary_key"):
            columns = constraint.get("columns", [])
            return tuple(str(column) for column in columns)
    return ()


def _format(items: Iterable[str]) -> str:
    return ", ".join(sorted(items)) or "none"


def main() -> None:
    errors: list[str] = []

    with connection.cursor() as cursor:
        database_tables = set(connection.introspection.table_names(cursor))

        for model in DOMAIN_MODELS:
            table = model._meta.db_table
            if model._meta.managed:
                errors.append(f"{table}: bridge model unexpectedly has managed=True")
                continue
            if table not in database_tables:
                errors.append(f"{table}: table missing from PostgreSQL")
                continue

            description = connection.introspection.get_table_description(cursor, table)
            actual_columns = {column.name for column in description}
            expected_columns = _columns(model)

            missing = expected_columns - actual_columns
            extra = actual_columns - expected_columns
            if missing or extra:
                errors.append(
                    f"{table}: column mismatch; missing={_format(missing)}; extra={_format(extra)}"
                )

            constraints = connection.introspection.get_constraints(cursor, table)
            actual_pk = _primary_key_columns(constraints)
            expected_pk = _pk_columns(model)
            if set(actual_pk) != set(expected_pk):
                errors.append(
                    f"{table}: primary-key mismatch; django={expected_pk!r}; database={actual_pk!r}"
                )

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))

    print(
        f"django schema parity OK: {len(DOMAIN_MODELS)} unmanaged Taskiller tables "
        "match PostgreSQL columns and primary keys"
    )


if __name__ == "__main__":
    main()
