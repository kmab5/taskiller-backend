"""Fail fast on release-contract drift that unit tests can miss."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from taskiller import __version__
from taskiller.api.health import EXPECTED_DB_REVISION
from taskiller.core.config import Settings
from taskiller.core.problems import PROBLEM_CODES
from taskiller.main import create_app

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "current.json"
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_PUBLIC_OPERATIONS = {
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


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    result: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in _HTTP_METHODS:
                result.append((path, method, operation))
    return result


def _literal_problem_codes() -> set[str]:
    codes: set[str] = set()
    for path in (ROOT / "src" / "taskiller").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name != "ApiError" or len(node.args) < 2:
                continue
            code_arg = node.args[1]
            if isinstance(code_arg, ast.Constant) and isinstance(code_arg.value, str):
                codes.add(code_arg.value)
    return codes


def main() -> None:
    settings = Settings(_env_file=None, env="test")
    schema = create_app(settings).openapi()
    errors: list[str] = []

    if schema.get("openapi") != "3.1.0":
        errors.append(f"OpenAPI version is {schema.get('openapi')!r}, expected '3.1.0'")
    if schema.get("info", {}).get("version") != __version__:
        errors.append("OpenAPI info.version does not match taskiller.__version__")

    alembic = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = alembic.get_heads()
    if heads != [EXPECTED_DB_REVISION]:
        errors.append(f"Readiness expects {EXPECTED_DB_REVISION}, but Alembic heads are {heads}")

    operations = _operations(schema)
    operation_ids = [operation.get("operationId") for _, _, operation in operations]
    missing_ids = [
        f"{method.upper()} {path}"
        for path, method, operation in operations
        if not operation.get("operationId")
    ]
    if missing_ids:
        errors.append("Operations without operationId: " + ", ".join(missing_ids))
    duplicates = sorted(
        {operation_id for operation_id in operation_ids if operation_ids.count(operation_id) > 1}
    )
    if duplicates:
        errors.append(
            "Duplicate operationId values: " + ", ".join(str(item) for item in duplicates)
        )

    for path, method, operation in operations:
        operation_id = operation["operationId"]
        if operation_id in _PUBLIC_OPERATIONS:
            continue
        if path.startswith(settings.api_prefix) and operation.get("security") != [
            {"bearerAuth": []}
        ]:
            errors.append(
                f"Protected operation lost bearerAuth: {method.upper()} {path} ({operation_id})"
            )

    literal_codes = _literal_problem_codes()
    if literal_codes != set(PROBLEM_CODES):
        missing = sorted(literal_codes - set(PROBLEM_CODES))
        unused = sorted(set(PROBLEM_CODES) - literal_codes)
        if missing:
            errors.append("Undocumented problem codes: " + ", ".join(missing))
        if unused:
            errors.append("Catalog codes without a literal ApiError: " + ", ".join(unused))
    if schema.get("x-taskiller-problem-codes") != sorted(PROBLEM_CODES):
        errors.append("OpenAPI problem-code catalog is incomplete or stale")

    if OPENAPI_PATH.exists():
        committed = json.loads(OPENAPI_PATH.read_text())
        if committed != schema:
            errors.append("openapi/current.json is stale; run `make openapi`")
    else:
        errors.append("openapi/current.json is missing")

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print(
        f"release contract OK: v{__version__}, "
        f"{len(schema['paths'])} paths, {len(operations)} operations"
    )


if __name__ == "__main__":
    main()
