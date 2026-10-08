"""Final Phase 10 audit: installed Taskiller backend is Django-only."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "taskiller"
FORBIDDEN_IMPORTS = ("fastapi", "sqlalchemy", "alembic")
FORBIDDEN_DEFAULT_DEPS = ("fastapi", "sqlalchemy", "alembic")


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def main() -> None:
    errors: list[str] = []

    for path in SRC.rglob("*.py"):
        for module in imported_modules(path):
            if module.startswith(FORBIDDEN_IMPORTS):
                errors.append(f"{path.relative_to(ROOT)} imports legacy dependency {module!r}")

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = [str(item).casefold() for item in pyproject["project"]["dependencies"]]
    for forbidden in FORBIDDEN_DEFAULT_DEPS:
        if any(item.startswith(forbidden) for item in deps):
            errors.append(f"default production dependencies still contain {forbidden!r}")

    for legacy_path in (
        ROOT / "src" / "taskiller" / "main.py",
        ROOT / "src" / "taskiller" / "db",
        ROOT / "alembic",
        ROOT / "alembic.ini",
    ):
        if legacy_path.exists():
            errors.append(
                f"legacy runtime path still exists in production tree: "
                f"{legacy_path.relative_to(ROOT)}"
            )

    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))

    print(
        "Phase 10 final audit OK: installable Taskiller backend has no "
        "FastAPI/SQLAlchemy/Alembic runtime imports or default dependencies"
    )


if __name__ == "__main__":
    main()
