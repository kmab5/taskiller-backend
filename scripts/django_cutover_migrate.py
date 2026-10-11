# ruff: noqa: E402
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

LEGACY_ALEMBIC_HEAD = "20260930_0007"


def _domain_adopted() -> bool:
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        if "django_migrations" not in tables:
            return False
        cursor.execute("SELECT 1 FROM django_migrations WHERE app = 'django_domain' LIMIT 1")
        return cursor.fetchone() is not None


def _existing_legacy_schema() -> bool:
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        return "users" in tables and "alembic_version" in tables


def _verify_legacy_schema() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cursor.fetchone()
        current = str(row[0]) if row else None
    if current != LEGACY_ALEMBIC_HEAD:
        raise RuntimeError(
            f"Existing Taskiller schema is at legacy revision {current!r}; "
            f"expected {LEGACY_ALEMBIC_HEAD!r} for one-time Django adoption."
        )


def main() -> None:
    if not _domain_adopted() and _existing_legacy_schema():
        _verify_legacy_schema()
        call_command(
            "migrate",
            interactive=False,
            fake_initial=True,
            verbosity=1,
        )
    else:
        call_command(
            "migrate",
            interactive=False,
            verbosity=1,
        )

    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if pending:
        names = ", ".join(
            f"{migration.app_label}:{migration.name}" for migration, _backwards in pending
        )
        raise RuntimeError(f"Django migrations remain pending: {names}")
    print("Django migrations/adoption OK")


if __name__ == "__main__":
    main()
