"""Final Django cutover contract audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402
from drf_spectacular.generators import SchemaGenerator  # noqa: E402

from taskiller import __version__  # noqa: E402
from taskiller.core.problems import PROBLEM_CODES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "openapi" / "current.json"
METHODS = {"get", "post", "put", "patch", "delete"}
PUBLIC = {
    "healthLive",
    "healthReady",
    "healthVersion",
    "register",
    "login",
    "refreshAccessToken",
    "confirmEmailVerification",
    "requestPasswordReset",
    "confirmPasswordReset",
    "downloadDataExport",
}


def _ops(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                result[(path, method)] = operation
    return result


def _secured(operation: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and "bearerAuth" in item
        for item in (operation.get("security") or [])
    )


def main() -> None:
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
    generated = SchemaGenerator().get_schema(request=None, public=True)
    assert generated is not None

    errors: list[str] = []
    if canonical.get("info", {}).get("version") != __version__:
        errors.append("canonical OpenAPI version differs from package version")
    if canonical.get("x-taskiller-problem-codes") != sorted(PROBLEM_CODES):
        errors.append("canonical problem-code catalog is stale")

    canonical_ops = _ops(canonical)
    django_ops = _ops(generated)

    # Health functions are plain Django views and intentionally do not participate
    # in drf-spectacular generation. All API operations must.
    api_expected = {
        key: value for key, value in canonical_ops.items() if key[0].startswith("/api/v1/")
    }
    for key, expected in api_expected.items():
        actual = django_ops.get(key)
        if actual is None:
            errors.append(f"Django missing {key[1].upper()} {key[0]}")
            continue
        if actual.get("operationId") != expected.get("operationId"):
            errors.append(f"operationId mismatch: {key}")
        operation_id = expected.get("operationId")
        should_secure = operation_id not in PUBLIC
        if _secured(actual) != should_secure:
            errors.append(f"security mismatch: {key}")

    unexpected = [
        key for key in django_ops if key[0].startswith("/api/v1/") and key not in api_expected
    ]
    if unexpected:
        errors.append(f"unexpected Django API operations: {unexpected!r}")

    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    pending = executor.migration_plan(targets)
    if pending:
        errors.append(
            "pending Django migrations: "
            + ", ".join(
                f"{migration.app_label}:{migration.name}" for migration, _backwards in pending
            )
        )

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))

    print(
        f"Django cutover contract OK: {len(api_expected)} API operations, "
        f"{len(canonical['paths'])} canonical paths"
    )


if __name__ == "__main__":
    main()
