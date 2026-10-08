from __future__ import annotations

from typing import Any

from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from taskiller import __version__
from taskiller.core.runtime import build_metadata


def _json(payload: dict[str, Any], *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _migration_state() -> tuple[str, str | None, bool]:
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    expected = ",".join(f"{app}:{name}" for app, name in sorted(targets))
    plan = executor.migration_plan(targets)
    if not plan:
        return expected, expected, True
    pending = ",".join(
        f"{migration.app_label}:{migration.name}" for migration, _backwards in plan[:8]
    )
    return expected, f"pending:{pending}", False


@require_GET
def live(_request: object) -> JsonResponse:
    return _json({"status": "ok"})


@require_GET
def ready(_request: object) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        expected, current, migrated = _migration_state()
    except (DatabaseError, OSError):
        return _json(
            {
                "status": "not_ready",
                "database": "unavailable",
                "migration": "unavailable",
                "expected_revision": "django:migrations",
                "current_revision": None,
            },
            status=503,
        )

    if not migrated:
        return _json(
            {
                "status": "not_ready",
                "database": "ok",
                "migration": "out_of_date",
                "expected_revision": expected,
                "current_revision": current,
            },
            status=503,
        )

    return _json(
        {
            "status": "ready",
            "database": "ok",
            "migration": "ok",
            "expected_revision": expected,
            "current_revision": current,
        }
    )


@require_GET
def version(_request: object) -> JsonResponse:
    metadata = build_metadata()
    return _json(
        {
            "version": __version__,
            "release_sha": metadata.release_sha,
            "release_branch": metadata.release_branch,
            "release_repository": metadata.release_repository,
        }
    )
