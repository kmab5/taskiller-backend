"""Audit Django production modules for direct legacy runtime imports."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DJANGO_ROOTS = [
    ROOT / "src" / "taskiller" / "django_api",
    ROOT / "src" / "taskiller" / "django_operations",
    ROOT / "src" / "taskiller" / "django_project",
]
FORBIDDEN = (
    "fastapi",
    "sqlalchemy",
    "alembic",
    "taskiller.main",
    "taskiller.db.session",
    "taskiller.operations.worker",
)


def imports(path: Path) -> list[str]:
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
    count = 0
    for root in DJANGO_ROOTS:
        for path in root.rglob("*.py"):
            count += 1
            for imported in imports(path):
                if imported.startswith(FORBIDDEN):
                    errors.append(
                        f"{path.relative_to(ROOT)} imports forbidden production dependency "
                        f"{imported!r}"
                    )
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print(
        f"Django production import audit OK: {count} modules have no direct "
        "FastAPI/SQLAlchemy/Alembic runtime imports"
    )


if __name__ == "__main__":
    main()
