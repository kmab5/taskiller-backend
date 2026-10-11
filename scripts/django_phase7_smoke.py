# ruff: noqa: E402
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.core.management import call_command
from django.test import Client

from taskiller.django_domain.models import DataExportRequest, OutboxJob


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    client = Client()
    email = f"django-phase7-{uuid4().hex}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        data={
            "email": email,
            "password": "Taskiller-phase7-password",
            "timezone": "Europe/Istanbul",
            "locale": "en",
        },
        content_type="application/json",
    )
    if register.status_code != 201:
        raise SystemExit("register failed")
    token = register.json()["accessToken"]
    auth = bearer(token)

    end = datetime.now(UTC) + timedelta(minutes=1)
    start = end - timedelta(days=1)
    query = f"?from={start.isoformat()}&to={end.isoformat()}"

    for path in (
        "/api/v1/analytics/summary",
        "/api/v1/analytics/work-types",
        "/api/v1/analytics/focus-patterns",
    ):
        response = client.get(path + query, **auth)
        if response.status_code != 200:
            raise SystemExit(
                f"analytics failed {path}: {response.status_code} {response.content!r}"
            )

    timeseries = client.get(
        "/api/v1/analytics/timeseries" + query + "&bucket=day",
        **auth,
    )
    if timeseries.status_code != 200:
        raise SystemExit("timeseries failed")

    export = client.post(
        "/api/v1/me/export-requests",
        HTTP_IDEMPOTENCY_KEY=f"phase7-export-{uuid4().hex}",
        **auth,
    )
    if export.status_code != 202:
        raise SystemExit("export request failed")

    export_id = export.json()["requestId"]
    call_command("taskiller_worker", once=True)

    row = DataExportRequest.objects.get(id=export_id)
    if row.status != "ready" or not row.archive_bytes:
        raise SystemExit(f"Django worker failed export: {row.status}")

    if not OutboxJob.objects.filter(
        job_type="retention",
        status__in=["queued", "running"],
    ).exists():
        raise SystemExit("retention job missing")

    print("django phase-7 smoke OK: Analytics + export worker + retention scheduling")


if __name__ == "__main__":
    main()
