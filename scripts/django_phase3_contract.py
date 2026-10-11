# ruff: noqa: E402
"""Compare migrated Django Auth/User API metadata with the canonical FastAPI OpenAPI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from drf_spectacular.generators import SchemaGenerator

ROOT = Path(__file__).resolve().parents[1]
FASTAPI_OPENAPI = ROOT / "openapi" / "current.json"
_METHODS = {"get", "post", "put", "patch", "delete"}
_MIGRATED_TAGS = {"Auth", "User"}


def _operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method in _METHODS:
                operations[(path, method)] = operation
    return operations


def _security(operation: dict[str, Any]) -> bool:
    security = operation.get("security") or []
    return any(isinstance(item, dict) and "bearerAuth" in item for item in security)


def main() -> None:
    canonical = json.loads(FASTAPI_OPENAPI.read_text(encoding="utf-8"))
    django_schema = SchemaGenerator().get_schema(request=None, public=True)
    assert django_schema is not None

    canonical_ops = _operations(canonical)
    django_ops = _operations(django_schema)

    expected = {
        key: operation
        for key, operation in canonical_ops.items()
        if set(operation.get("tags", [])) & _MIGRATED_TAGS
    }

    errors: list[str] = []
    for key, operation in expected.items():
        if key not in django_ops:
            errors.append(f"missing Django operation: {key[1].upper()} {key[0]}")
            continue
        migrated = django_ops[key]
        if migrated.get("operationId") != operation.get("operationId"):
            errors.append(
                f"{key[1].upper()} {key[0]} operationId mismatch: "
                f"django={migrated.get('operationId')!r} "
                f"fastapi={operation.get('operationId')!r}"
            )
        if _security(migrated) != _security(operation):
            errors.append(
                f"{key[1].upper()} {key[0]} security mismatch: "
                f"django={migrated.get('security')!r} "
                f"fastapi={operation.get('security')!r}"
            )

    unexpected = [
        key
        for key, operation in django_ops.items()
        if (
            key[0].startswith("/api/v1/")
            and key not in expected
            and set(operation.get("tags", [])) & _MIGRATED_TAGS
        )
    ]
    if unexpected:
        errors.append(
            "unexpected Auth/User migration operations: "
            + ", ".join(f"{method.upper()} {path}" for path, method in unexpected)
        )

    if errors:
        raise SystemExit("\\n".join(f"- {error}" for error in errors))

    print(
        f"django auth/user contract parity OK: {len(expected)} operations "
        "match canonical paths, operationIds, and auth/public status"
    )


if __name__ == "__main__":
    main()
