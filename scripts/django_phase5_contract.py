# ruff: noqa: E402
"""Compare migrated Django Auth/User/Work/Focus metadata with FastAPI OpenAPI."""

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
_MIGRATED_TAGS = {"Auth", "User", "Work", "Focus"}


def _operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method in _METHODS:
                result[(path, method)] = operation
    return result


def _security(operation: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and "bearerAuth" in item
        for item in (operation.get("security") or [])
    )


def main() -> None:
    canonical = json.loads(FASTAPI_OPENAPI.read_text(encoding="utf-8"))
    django_schema = SchemaGenerator().get_schema(request=None, public=True)
    assert django_schema is not None

    canonical_ops = _operations(canonical)
    django_ops = _operations(django_schema)
    expected = {
        key: op for key, op in canonical_ops.items() if set(op.get("tags", [])) & _MIGRATED_TAGS
    }

    errors = []
    for key, operation in expected.items():
        migrated = django_ops.get(key)
        if migrated is None:
            errors.append(f"missing {key[1].upper()} {key[0]}")
            continue
        if migrated.get("operationId") != operation.get("operationId"):
            errors.append(f"operationId mismatch {key}")
        if _security(migrated) != _security(operation):
            errors.append(f"security mismatch {key}")
        if set(migrated.get("tags", [])) != set(operation.get("tags", [])):
            errors.append(f"tag mismatch {key}")

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print(f"django phase-5 contract parity OK: {len(expected)} migrated operations")


if __name__ == "__main__":
    main()
