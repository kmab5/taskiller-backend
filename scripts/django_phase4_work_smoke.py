# ruff: noqa: E402
"""Exercise Django Work API behavior on the Alembic-owned test schema."""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.test import Client

from taskiller.django_domain.models import WorkItem


def _bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    client = Client()
    email = f"django-phase4-{uuid4().hex}@example.com"
    password = "Taskiller-phase4-password"

    register = client.post(
        "/api/v1/auth/register",
        data={
            "email": email,
            "password": password,
            "displayName": "Django Phase 4",
            "timezone": "Europe/Istanbul",
            "locale": "en",
        },
        content_type="application/json",
    )
    if register.status_code != 201:
        raise SystemExit(f"register failed: {register.status_code} {register.content!r}")
    token = register.json()["accessToken"]
    auth = _bearer(token)

    work_types = client.get("/api/v1/work-types", **auth)
    if work_types.status_code != 200 or not work_types.json()["items"]:
        raise SystemExit(f"work type list failed: {work_types.status_code} {work_types.content!r}")
    programming = next(
        (item for item in work_types.json()["items"] if item["slug"] == "programming"),
        work_types.json()["items"][0],
    )

    custom_key = f"phase4-type-{uuid4().hex}"
    custom = client.post(
        "/api/v1/work-types",
        data={
            "slug": f"phase4-{uuid4().hex[:12]}",
            "displayName": "Phase 4 Custom",
            "description": "Created by Django Phase 4 smoke",
            "characteristics": {
                "cognitiveDemand": "medium",
                "interruptionSensitivity": "medium",
                "continuityNeed": "medium",
                "repetitiveness": "low",
                "physicality": "sedentary",
                "learningMode": "none",
            },
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=custom_key,
        **auth,
    )
    if custom.status_code != 201:
        raise SystemExit(f"custom work type failed: {custom.status_code} {custom.content!r}")
    custom_id = custom.json()["id"]
    custom_etag = custom.headers.get("ETag")
    if not custom_etag:
        raise SystemExit("custom Work Type returned no ETag")

    project = client.post(
        "/api/v1/work-items",
        data={
            "kind": "project",
            "name": "Phase 4 Project",
            "status": "ready",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase4-project-{uuid4().hex}",
        **auth,
    )
    if project.status_code != 201:
        raise SystemExit(f"project create failed: {project.status_code} {project.content!r}")
    project_id = project.json()["id"]

    sprint = client.post(
        "/api/v1/work-items",
        data={
            "kind": "sprint",
            "parentId": project_id,
            "name": "Phase 4 Sprint",
            "status": "ready",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase4-sprint-{uuid4().hex}",
        **auth,
    )
    if sprint.status_code != 201:
        raise SystemExit(f"sprint create failed: {sprint.status_code} {sprint.content!r}")
    sprint_id = sprint.json()["id"]

    chore_one = client.post(
        "/api/v1/work-items",
        data={
            "kind": "chore",
            "parentId": sprint_id,
            "workTypeId": programming["id"],
            "name": "First Phase 4 Chore",
            "status": "ready",
            "estimatedEffortSeconds": 1800,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase4-chore1-{uuid4().hex}",
        **auth,
    )
    chore_two = client.post(
        "/api/v1/work-items",
        data={
            "kind": "chore",
            "parentId": sprint_id,
            "workTypeId": programming["id"],
            "name": "Second Phase 4 Chore",
            "status": "draft",
            "estimatedEffortSeconds": 900,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase4-chore2-{uuid4().hex}",
        **auth,
    )
    if chore_one.status_code != 201 or chore_two.status_code != 201:
        raise SystemExit("chore creation failed")

    chore_one_id = chore_one.json()["id"]
    chore_two_id = chore_two.json()["id"]
    chore_one_etag = chore_one.headers.get("ETag")

    tree = client.get(
        f"/api/v1/work-items/{project_id}/tree",
        **auth,
    )
    if tree.status_code != 200:
        raise SystemExit(f"tree failed: {tree.status_code} {tree.content!r}")
    if tree.json()["children"][0]["id"] != sprint_id:
        raise SystemExit("tree hierarchy mismatch")

    next_action = client.get(
        f"/api/v1/projects/{project_id}/next-action",
        **auth,
    )
    if next_action.status_code != 200 or next_action.json()["nextAction"]["id"] != chore_one_id:
        raise SystemExit(f"next action mismatch: {next_action.status_code} {next_action.content!r}")

    update = client.patch(
        f"/api/v1/work-items/{chore_one_id}",
        data={
            "status": "in_progress",
            "priority": 5,
        },
        content_type="application/json",
        HTTP_IF_MATCH=chore_one_etag,
        **auth,
    )
    if update.status_code != 200 or update.json()["status"] != "in_progress":
        raise SystemExit(f"work update failed: {update.status_code} {update.content!r}")

    stale = client.patch(
        f"/api/v1/work-items/{chore_one_id}",
        data={"priority": 4},
        content_type="application/json",
        HTTP_IF_MATCH=chore_one_etag,
        **auth,
    )
    if stale.status_code != 412:
        raise SystemExit(f"stale ETag expected 412, got {stale.status_code}")

    reorder = client.post(
        f"/api/v1/work-items/{chore_two_id}/reorder",
        data={"beforeId": chore_one_id},
        content_type="application/json",
        HTTP_IF_MATCH=chore_two.headers.get("ETag"),
        HTTP_IDEMPOTENCY_KEY=f"phase4-reorder-{uuid4().hex}",
        **auth,
    )
    if reorder.status_code != 200:
        raise SystemExit(f"reorder failed: {reorder.status_code} {reorder.content!r}")

    children = client.get(
        f"/api/v1/work-items/{sprint_id}/children",
        **auth,
    )
    ids = [item["id"] for item in children.json()["items"]]
    if ids[:2] != [chore_two_id, chore_one_id]:
        raise SystemExit(f"reorder result mismatch: {ids!r}")

    cannot_delete_parent = client.delete(
        f"/api/v1/work-items/{sprint_id}",
        HTTP_IF_MATCH=sprint.headers.get("ETag"),
        **auth,
    )
    if cannot_delete_parent.status_code != 409:
        raise SystemExit("deleting a parent with children should return 409")

    if not WorkItem.objects.filter(id=chore_one_id).exists():
        raise SystemExit("Django ORM did not persist work item")

    type_update = client.patch(
        f"/api/v1/work-types/{custom_id}",
        data={"displayName": "Phase 4 Custom Updated"},
        content_type="application/json",
        HTTP_IF_MATCH=custom_etag,
        **auth,
    )
    if type_update.status_code != 200:
        raise SystemExit(
            f"work type update failed: {type_update.status_code} {type_update.content!r}"
        )
    type_delete = client.delete(
        f"/api/v1/work-types/{custom_id}",
        HTTP_IF_MATCH=type_update.headers.get("ETag"),
        **auth,
    )
    if type_delete.status_code != 204:
        raise SystemExit(f"work type delete failed: {type_delete.status_code}")

    print(
        "django phase-4 Work smoke OK: Work Types, Project/Sprint/Chore CRUD, "
        "tree, next action, ETags, reordering, parent-delete protection"
    )


if __name__ == "__main__":
    main()
