"""Exercise Django Focus behavior on the Alembic-owned test schema."""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.test import Client  # noqa: E402


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    client = Client()
    email = f"django-phase5-{uuid4().hex}@example.com"
    password = "Taskiller-phase5-password"
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
    token = register.json()["accessToken"]
    auth = bearer(token)

    types = client.get("/api/v1/work-types", **auth).json()["items"]
    programming = next((item for item in types if item["slug"] == "programming"), types[0])

    chore = client.post(
        "/api/v1/work-items",
        data={
            "kind": "chore",
            "workTypeId": programming["id"],
            "name": "Phase 5 focus chore",
            "status": "ready",
            "estimatedEffortSeconds": 3600,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase5-chore-{uuid4().hex}",
        **auth,
    )
    if chore.status_code != 201:
        raise SystemExit(f"chore failed: {chore.content!r}")
    chore_id = chore.json()["id"]

    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        data={
            "workItemId": chore_id,
            "availableTimeSeconds": 3600,
            "preferredStrategy": "auto",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase5-rec-{uuid4().hex}",
        **auth,
    )
    if recommendation.status_code != 201:
        raise SystemExit(
            f"recommendation failed: {recommendation.status_code} {recommendation.content!r}"
        )
    rec = recommendation.json()
    if not rec["plan"]["segments"]:
        raise SystemExit("recommendation returned no segments")

    plan = client.post(
        "/api/v1/focus-plans",
        data={
            "workItemId": chore_id,
            "recommendationId": rec["id"],
            "source": "recommendation",
            "name": "Phase 5 Plan",
            "template": False,
            "segments": rec["plan"]["segments"],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase5-plan-{uuid4().hex}",
        **auth,
    )
    if plan.status_code != 201:
        raise SystemExit(f"plan create failed: {plan.status_code} {plan.content!r}")
    plan_id = plan.json()["id"]
    etag = plan.headers.get("ETag")
    if not etag:
        raise SystemExit("focus plan returned no ETag")

    fetched = client.get(f"/api/v1/focus-plans/{plan_id}", **auth)
    if fetched.status_code != 200:
        raise SystemExit("focus plan fetch failed")

    updated = client.patch(
        f"/api/v1/focus-plans/{plan_id}",
        data={"name": "Phase 5 Plan Updated"},
        content_type="application/json",
        HTTP_IF_MATCH=etag,
        **auth,
    )
    if updated.status_code != 200 or updated.json()["name"] != "Phase 5 Plan Updated":
        raise SystemExit("focus plan update failed")

    stale = client.patch(
        f"/api/v1/focus-plans/{plan_id}",
        data={"name": "stale"},
        content_type="application/json",
        HTTP_IF_MATCH=etag,
        **auth,
    )
    if stale.status_code != 412:
        raise SystemExit(f"stale focus ETag expected 412, got {stale.status_code}")

    listing = client.get(
        f"/api/v1/focus-plans?workItemId={chore_id}",
        **auth,
    )
    if listing.status_code != 200 or not listing.json()["items"]:
        raise SystemExit("focus plan list failed")

    delete = client.delete(
        f"/api/v1/focus-plans/{plan_id}",
        HTTP_IF_MATCH=updated.headers.get("ETag"),
        **auth,
    )
    if delete.status_code != 204:
        raise SystemExit("focus plan delete failed")

    print(
        "django phase-5 Focus smoke OK: recommendation, plan create/get/update/list/delete, ETags"
    )


if __name__ == "__main__":
    main()
