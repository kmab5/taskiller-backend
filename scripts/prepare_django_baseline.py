# ruff: noqa: E402
"""Generate the one-time Django initial migration for the existing Taskiller schema.

Run this locally after Phase 8 is applied and dependencies are synced, then review and
commit the generated migration. Never generate migrations dynamically in Render.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.core.management import call_command

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "src" / "taskiller" / "django_domain" / "migrations"


def main() -> None:
    MIGRATIONS.mkdir(parents=True, exist_ok=True)
    (MIGRATIONS / "__init__.py").touch()

    existing = [path for path in MIGRATIONS.glob("0*.py") if path.name != "__init__.py"]
    if existing:
        print("Django domain baseline already exists:")
        for path in sorted(existing):
            print(f"  {path.relative_to(ROOT)}")
        call_command(
            "makemigrations",
            "django_domain",
            check=True,
            dry_run=True,
            verbosity=1,
        )
        return

    call_command(
        "makemigrations",
        "django_domain",
        name="existing_schema_baseline",
        verbosity=2,
    )
    print("\nReview the generated initial migration carefully and commit it before deployment.")


if __name__ == "__main__":
    main()
