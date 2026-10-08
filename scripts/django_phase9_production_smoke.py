"""Final Django production-shaped smoke test."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.test import Client  # noqa: E402


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    client = Client()

    for path in ("/health/live", "/health/ready", "/openapi.json"):
        response = client.get(path)
        if response.status_code != 200:
            raise SystemExit(f"{path} failed: {response.status_code} {response.content!r}")

    admin = client.get("/admin/")
    if admin.status_code not in {200, 302}:
        raise SystemExit(f"admin failed: {admin.status_code}")

    email = f"phase9-{uuid4().hex}@example.com"
    password = "Taskiller-phase9-password"
    register = client.post(
        "/api/v1/auth/register",
        data={
            "email": email,
            "password": password,
            "timezone": "Europe/Istanbul",
            "locale": "en",
        },
        content_type="application/json",
    )
    if register.status_code != 201:
        raise SystemExit(f"register failed: {register.content!r}")
    auth = bearer(register.json()["accessToken"])

    if client.get("/api/v1/me", **auth).status_code != 200:
        raise SystemExit("profile failed")

    types = client.get("/api/v1/work-types", **auth)
    if types.status_code != 200:
        raise SystemExit("work types failed")
    items = types.json()["items"]
    work_type = next((item for item in items if item["slug"] == "programming"), items[0])

    chore = client.post(
        "/api/v1/work-items",
        data={
            "kind": "chore",
            "workTypeId": work_type["id"],
            "name": "Phase 9 production smoke",
            "status": "ready",
            "estimatedEffortSeconds": 900,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase9-work-{uuid4().hex}",
        **auth,
    )
    if chore.status_code != 201:
        raise SystemExit(f"work create failed: {chore.content!r}")
    work_id = chore.json()["id"]

    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        data={
            "workItemId": work_id,
            "availableTimeSeconds": 900,
            "preferredStrategy": "auto",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase9-rec-{uuid4().hex}",
        **auth,
    )
    if recommendation.status_code != 201:
        raise SystemExit(f"focus recommendation failed: {recommendation.content!r}")

    end = datetime.now(UTC) + timedelta(minutes=1)
    start = end - timedelta(hours=1)
    analytics = client.get(
        f"/api/v1/analytics/summary?from={start.isoformat()}&to={end.isoformat()}",
        **auth,
    )
    if analytics.status_code != 200:
        raise SystemExit(f"analytics failed: {analytics.content!r}")

    print("Phase 9 production smoke OK: health, OpenAPI, admin, auth, Work, Focus, Analytics")


if __name__ == "__main__":
    main()
