"""Smoke the cumulative Django Phase 1 + 2 foundation."""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.contrib import admin  # noqa: E402
from django.test import Client  # noqa: E402

from taskiller.django_domain import models as domain  # noqa: E402


def main() -> None:
    client = Client()

    live = client.get("/health/live")
    if live.status_code != 200 or live.json() != {"status": "ok"}:
        raise SystemExit(f"Django liveness failed: {live.status_code} {live.content!r}")

    ready = client.get("/health/ready")
    if ready.status_code != 200:
        raise SystemExit(f"Django readiness failed: {ready.status_code} {ready.content!r}")

    if domain.WorkItem._meta.managed:
        raise SystemExit("WorkItem must remain unmanaged in Phase 2")

    if domain.TaskillerUser not in admin.site._registry:
        raise SystemExit("TaskillerUser is not registered in Django Admin")
    if domain.WorkItem not in admin.site._registry:
        raise SystemExit("WorkItem is not registered in Django Admin")

    if domain.IdempotencyRecord in admin.site._registry:
        raise SystemExit("Composite-PK IdempotencyRecord must not be in Django Admin")

    print("django phase-2 smoke OK: health, unmanaged domain bridge, read-only admin registrations")


if __name__ == "__main__":
    main()
