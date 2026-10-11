"""Prove Django ORM and SQLAlchemy read the same Taskiller rows."""

from __future__ import annotations

import os
from datetime import date, datetime
from uuid import UUID

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from sqlalchemy import create_engine, func, select  # noqa: E402
from taskiller.db.models import (  # noqa: E402
    AuthSession as SAAuthSession,
)
from taskiller.db.models import (
    EmailVerificationToken as SAEmailVerificationToken,
)
from taskiller.db.models import (
    IdempotencyRecord as SAIdempotencyRecord,
)
from taskiller.db.models import (
    PasswordResetToken as SAPasswordResetToken,
)
from taskiller.db.models import (
    RefreshToken as SARefreshToken,
)
from taskiller.db.models import (
    User as SAUser,
)
from taskiller.db.models import (
    UserPreferences as SAUserPreferences,
)
from taskiller.execution.models import (  # noqa: E402
    ExecutionSessionModel as SAExecutionSession,
)
from taskiller.execution.models import (
    SessionEventModel as SASessionEvent,
)
from taskiller.execution.models import (
    SessionReviewModel as SASessionReview,
)
from taskiller.focus.models import (  # noqa: E402
    FocusPlanModel as SAFocusPlan,
)
from taskiller.focus.models import (
    FocusPlanRecommendationModel as SAFocusPlanRecommendation,
)
from taskiller.focus.models import (
    FocusPlanSegmentModel as SAFocusPlanSegment,
)
from taskiller.operations.models import (  # noqa: E402
    AccountDeletionRequest as SAAccountDeletionRequest,
)
from taskiller.operations.models import (
    DataExportRequest as SADataExportRequest,
)
from taskiller.operations.models import (
    OutboxJob as SAOutboxJob,
)
from taskiller.operations.models import (
    RateLimitBucket as SARateLimitBucket,
)
from taskiller.operations.models import (
    SecurityEvent as SASecurityEvent,
)
from taskiller.work.models import WorkItem as SAWorkItem  # noqa: E402
from taskiller.work.models import WorkType as SAWorkType  # noqa: E402

from taskiller.django_domain import models as dj  # noqa: E402

PAIRS = (
    (dj.TaskillerUser, SAUser),
    (dj.UserPreferences, SAUserPreferences),
    (dj.AuthSession, SAAuthSession),
    (dj.RefreshToken, SARefreshToken),
    (dj.EmailVerificationToken, SAEmailVerificationToken),
    (dj.PasswordResetToken, SAPasswordResetToken),
    (dj.IdempotencyRecord, SAIdempotencyRecord),
    (dj.WorkType, SAWorkType),
    (dj.WorkItem, SAWorkItem),
    (dj.FocusPlanRecommendation, SAFocusPlanRecommendation),
    (dj.FocusPlan, SAFocusPlan),
    (dj.FocusPlanSegment, SAFocusPlanSegment),
    (dj.ExecutionSession, SAExecutionSession),
    (dj.SessionEvent, SASessionEvent),
    (dj.SessionReview, SASessionReview),
    (dj.DataExportRequest, SADataExportRequest),
    (dj.AccountDeletionRequest, SAAccountDeletionRequest),
    (dj.OutboxJob, SAOutboxJob),
    (dj.RateLimitBucket, SARateLimitBucket),
    (dj.SecurityEvent, SASecurityEvent),
)


def _normalize(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, bytes):
        return value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item) for item in value)
    return value


def _django_first(model: type[object]) -> dict[str, object] | None:
    fields = [
        field
        for field in model._meta.local_fields  # type: ignore[attr-defined]
        if field.column is not None
    ]
    attnames = [field.attname for field in fields]
    pk_attnames = [
        field.attname
        for field in model._meta.pk_fields  # type: ignore[attr-defined]
    ]
    row = model.objects.order_by(*pk_attnames).values(*attnames).first()  # type: ignore[attr-defined]
    if row is None:
        return None
    by_column = {field.column: _normalize(row[field.attname]) for field in fields}
    return by_column


def main() -> None:
    database_url = os.environ.get(
        "TASKILLER_DATABASE_URL",
        "postgresql+psycopg://taskiller:taskiller@localhost:5432/taskiller",
    )
    engine = create_engine(database_url)
    errors: list[str] = []

    try:
        with engine.connect() as sqlalchemy_connection:
            for django_model, sqlalchemy_model in PAIRS:
                table = sqlalchemy_model.__table__
                table_name = table.name

                django_count = django_model.objects.count()
                sqlalchemy_count = sqlalchemy_connection.scalar(
                    select(func.count()).select_from(table)
                )
                if django_count != sqlalchemy_count:
                    errors.append(
                        f"{table_name}: count mismatch "
                        f"django={django_count} sqlalchemy={sqlalchemy_count}"
                    )
                    continue

                if django_count == 0:
                    continue

                django_row = _django_first(django_model)
                pk_columns = [
                    field.column
                    for field in django_model._meta.pk_fields
                    if field.column is not None
                ]
                statement = select(table)
                if pk_columns:
                    statement = statement.order_by(*(table.c[column] for column in pk_columns))
                raw_row = sqlalchemy_connection.execute(statement.limit(1)).mappings().first()
                if raw_row is None or django_row is None:
                    errors.append(f"{table_name}: failed to sample first row")
                    continue

                sqlalchemy_row = {
                    column.name: _normalize(raw_row[column.name]) for column in table.columns
                }
                if django_row != sqlalchemy_row:
                    differing = sorted(
                        key
                        for key in set(django_row) | set(sqlalchemy_row)
                        if django_row.get(key) != sqlalchemy_row.get(key)
                    )
                    errors.append(
                        f"{table_name}: sampled row differs in columns: " + ", ".join(differing)
                    )
    finally:
        engine.dispose()

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))

    print(
        f"django/sqlalchemy row parity OK: {len(PAIRS)} tables have matching "
        "counts and sampled rows"
    )


if __name__ == "__main__":
    main()
