# ruff: noqa: E402
"""Verify the committed/adopted Django domain migration baseline."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "src" / "taskiller" / "django_domain" / "migrations"


def main() -> None:
    errors: list[str] = []
    initial = sorted(MIGRATIONS.glob("0001_*.py"))
    if len(initial) != 1:
        errors.append(
            "expected exactly one committed django_domain 0001 migration; "
            f"found {[path.name for path in initial]!r}"
        )

    unmanaged = [
        model._meta.label
        for model in apps.get_app_config("django_domain").get_models()
        if not model._meta.managed
    ]
    if unmanaged:
        errors.append("unmanaged models remain: " + ", ".join(unmanaged))

    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    pending = executor.migration_plan(targets)
    if pending:
        errors.append(
            "pending migrations: "
            + ", ".join(
                f"{migration.app_label}:{migration.name}" for migration, _backwards in pending
            )
        )

    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        required = {
            "django_migrations",
            "users",
            "work_items",
            "focus_plans",
            "execution_sessions",
            "outbox_jobs",
        }
        missing = sorted(required - tables)
        if missing:
            errors.append("missing adopted tables: " + ", ".join(missing))
        if "django_migrations" in tables:
            cursor.execute("SELECT COUNT(*) FROM django_migrations WHERE app = 'django_domain'")
            if int(cursor.fetchone()[0]) < 1:
                errors.append("django_domain baseline not recorded in django_migrations")

        for model in apps.get_app_config("django_domain").get_models():
            if model._meta.db_table not in tables:
                continue
            actual = connection.introspection.get_constraints(cursor, model._meta.db_table)
            for declared in [*model._meta.constraints, *model._meta.indexes]:
                if declared.name not in actual:
                    errors.append(f"missing database constraint/index: {declared.name}")

        cursor.execute("""
            SELECT tgname FROM pg_trigger
            WHERE NOT tgisinternal AND tgenabled <> 'D'
            AND tgrelid IN (
                SELECT oid FROM pg_class WHERE relnamespace = current_schema()::regnamespace
            )
        """)
        actual_triggers = {row[0] for row in cursor.fetchall()}
        for table in (
            "work_items",
            "focus_plan_recommendations",
            "focus_plans",
            "focus_plan_segments",
            "execution_sessions",
            "session_events",
            "session_reviews",
        ):
            name = f"tk_{table}_relationships"
            if name not in actual_triggers:
                errors.append(f"missing database trigger: {name}")
        if "tk_session_event_history" not in actual_triggers:
            errors.append("missing database trigger: tk_session_event_history")
        if "tk_security_event_history" not in actual_triggers:
            errors.append("missing database trigger: tk_security_event_history")

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))

    print(
        "Django baseline audit OK: committed baseline, managed models, "
        "constraints/indexes/triggers present, no pending migrations"
    )


if __name__ == "__main__":
    main()
