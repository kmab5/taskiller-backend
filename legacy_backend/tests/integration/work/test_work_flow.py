import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from taskiller.auth.email import MemoryEmailSender
from taskiller.core.config import Settings
from taskiller.main import create_app

pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("TASKILLER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("TASKILLER_TEST_DATABASE_URL is not configured")
    return url


@pytest.fixture(autouse=True)
def clean_database() -> None:
    engine = create_engine(_database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE password_reset_tokens, email_verification_tokens, "
                "refresh_tokens, auth_sessions, user_preferences"
            )
        )
        connection.execute(text("DELETE FROM users"))
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=_database_url(),
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
    )
    with TestClient(create_app(settings, email_sender=MemoryEmailSender())) as test_client:
        yield test_client


def _register(client: TestClient, email: str = "person@example.com") -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["accessToken"])


def _auth(access: str, **headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", **headers}


def _post_work_item(
    client: TestClient,
    access: str,
    body: dict[str, object],
    *,
    key: str | None = None,
) -> Response:
    return client.post(
        "/api/v1/work-items",
        headers=_auth(access, **{"Idempotency-Key": key or str(uuid4())}),
        json=body,
    )


def test_work_types_include_presets_and_custom_types_are_idempotent(client: TestClient) -> None:
    access = _register(client)
    listed = client.get("/api/v1/work-types", headers=_auth(access))
    assert listed.status_code == 200, listed.text
    system = next(item for item in listed.json()["items"] if item["slug"] == "programming")
    assert system["system"] is True

    key = str(uuid4())
    body = {
        "slug": "research_notes",
        "displayName": "Research Notes",
        "characteristics": {
            "cognitiveDemand": "high",
            "interruptionSensitivity": "medium",
            "continuityNeed": "medium",
            "repetitiveness": "low",
            "physicality": "sedentary",
            "learningMode": "acquisition",
        },
    }
    created = client.post(
        "/api/v1/work-types",
        headers=_auth(access, **{"Idempotency-Key": key}),
        json=body,
    )
    assert created.status_code == 201, created.text
    replay = client.post(
        "/api/v1/work-types",
        headers=_auth(access, **{"Idempotency-Key": key}),
        json=body,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == created.json()["id"]

    conflict = client.post(
        "/api/v1/work-types",
        headers=_auth(access, **{"Idempotency-Key": key}),
        json={**body, "displayName": "Different"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_key_reused"

    custom_etag = created.headers["etag"]
    changed = client.patch(
        f"/api/v1/work-types/{created.json()['id']}",
        headers=_auth(access, **{"If-Match": custom_etag}),
        json={"displayName": "Research / Notes"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.headers["etag"] != custom_etag

    stale = client.patch(
        f"/api/v1/work-types/{created.json()['id']}",
        headers=_auth(access, **{"If-Match": custom_etag}),
        json={"displayName": "Stale"},
    )
    assert stale.status_code == 412

    built_in = client.get(f"/api/v1/work-types/{system['id']}", headers=_auth(access))
    immutable = client.patch(
        f"/api/v1/work-types/{system['id']}",
        headers=_auth(access, **{"If-Match": built_in.headers["etag"]}),
        json={"displayName": "Nope"},
    )
    assert immutable.status_code == 403
    assert immutable.json()["code"] == "system_work_type_immutable"


def test_hierarchy_tree_and_next_action(client: TestClient) -> None:
    access = _register(client)
    project = _post_work_item(
        client,
        access,
        {"kind": "project", "name": "Taskiller", "status": "ready"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    sprint = _post_work_item(
        client,
        access,
        {
            "kind": "sprint",
            "parentId": project_id,
            "name": "Backend",
            "status": "ready",
        },
    )
    assert sprint.status_code == 201, sprint.text
    sprint_id = sprint.json()["id"]

    first = _post_work_item(
        client,
        access,
        {
            "kind": "chore",
            "parentId": sprint_id,
            "name": "Database",
            "status": "ready",
        },
    )
    second = _post_work_item(
        client,
        access,
        {
            "kind": "chore",
            "parentId": sprint_id,
            "name": "REST API",
            "status": "ready",
        },
    )
    assert first.status_code == second.status_code == 201

    invalid_sprint = _post_work_item(
        client,
        access,
        {"kind": "sprint", "name": "Orphan Sprint"},
    )
    assert invalid_sprint.status_code == 409
    assert invalid_sprint.json()["code"] == "invalid_work_hierarchy"

    invalid_child = _post_work_item(
        client,
        access,
        {
            "kind": "chore",
            "parentId": first.json()["id"],
            "name": "Nested Chore",
        },
    )
    assert invalid_child.status_code == 409

    tree = client.get(f"/api/v1/work-items/{project_id}/tree", headers=_auth(access))
    assert tree.status_code == 200
    assert tree.json()["children"][0]["id"] == sprint_id
    assert [item["name"] for item in tree.json()["children"][0]["children"]] == [
        "Database",
        "REST API",
    ]

    next_action = client.get(
        f"/api/v1/projects/{project_id}/next-action",
        headers=_auth(access),
    )
    assert next_action.status_code == 200
    assert next_action.json()["nextAction"]["id"] == first.json()["id"]

    completed_project = client.patch(
        f"/api/v1/work-items/{project_id}",
        headers=_auth(access, **{"If-Match": project.headers["etag"]}),
        json={"status": "completed"},
    )
    assert completed_project.status_code == 200
    no_next_action = client.get(
        f"/api/v1/projects/{project_id}/next-action",
        headers=_auth(access),
    )
    assert no_next_action.status_code == 200
    assert no_next_action.json()["nextAction"] is None


def test_state_transitions_soft_delete_and_parent_delete_guard(client: TestClient) -> None:
    access = _register(client)
    chore = _post_work_item(client, access, {"kind": "chore", "name": "One task"})
    assert chore.status_code == 201
    item_id = chore.json()["id"]

    ready = client.patch(
        f"/api/v1/work-items/{item_id}",
        headers=_auth(access, **{"If-Match": chore.headers["etag"]}),
        json={"status": "ready"},
    )
    assert ready.status_code == 200, ready.text
    completed = client.patch(
        f"/api/v1/work-items/{item_id}",
        headers=_auth(access, **{"If-Match": ready.headers["etag"]}),
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["completedAt"] is not None

    invalid = client.patch(
        f"/api/v1/work-items/{item_id}",
        headers=_auth(access, **{"If-Match": completed.headers["etag"]}),
        json={"status": "in_progress"},
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "work_item_state_conflict"

    reopened = client.patch(
        f"/api/v1/work-items/{item_id}",
        headers=_auth(access, **{"If-Match": completed.headers["etag"]}),
        json={"status": "ready"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["completedAt"] is None

    deleted = client.delete(
        f"/api/v1/work-items/{item_id}",
        headers=_auth(access, **{"If-Match": reopened.headers["etag"]}),
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/work-items/{item_id}", headers=_auth(access)).status_code == 404

    including_deleted = client.get(
        "/api/v1/work-items?includeDeleted=true",
        headers=_auth(access),
    )
    deleted_row = next(item for item in including_deleted.json()["items"] if item["id"] == item_id)
    assert deleted_row["deletedAt"] is not None

    project = _post_work_item(client, access, {"kind": "project", "name": "Project"})
    child = _post_work_item(
        client,
        access,
        {"kind": "chore", "parentId": project.json()["id"], "name": "Child"},
    )
    assert child.status_code == 201
    guarded = client.delete(
        f"/api/v1/work-items/{project.json()['id']}",
        headers=_auth(access, **{"If-Match": project.headers["etag"]}),
    )
    assert guarded.status_code == 409
    assert guarded.json()["code"] == "work_item_has_children"


def test_reorder_uses_sibling_positions_and_is_idempotent(client: TestClient) -> None:
    access = _register(client)
    project = _post_work_item(client, access, {"kind": "project", "name": "Project"})
    project_id = project.json()["id"]
    first = _post_work_item(
        client,
        access,
        {"kind": "chore", "parentId": project_id, "name": "First"},
    )
    second = _post_work_item(
        client,
        access,
        {"kind": "chore", "parentId": project_id, "name": "Second"},
    )
    third = _post_work_item(
        client,
        access,
        {"kind": "chore", "parentId": project_id, "name": "Third"},
    )
    key = str(uuid4())
    body = {"beforeId": first.json()["id"]}
    reordered = client.post(
        f"/api/v1/work-items/{third.json()['id']}/reorder",
        headers=_auth(
            access,
            **{"Idempotency-Key": key, "If-Match": third.headers["etag"]},
        ),
        json=body,
    )
    assert reordered.status_code == 200, reordered.text

    replay = client.post(
        f"/api/v1/work-items/{third.json()['id']}/reorder",
        headers=_auth(
            access,
            **{"Idempotency-Key": key, "If-Match": third.headers["etag"]},
        ),
        json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == reordered.json()

    children = client.get(
        f"/api/v1/work-items/{project_id}/children",
        headers=_auth(access),
    )
    assert [item["name"] for item in children.json()["items"]] == [
        "Third",
        "First",
        "Second",
    ]

    reused = client.post(
        f"/api/v1/work-items/{third.json()['id']}/reorder",
        headers=_auth(
            access,
            **{"Idempotency-Key": key, "If-Match": reordered.headers["etag"]},
        ),
        json={"afterId": second.json()["id"]},
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "idempotency_key_reused"


def test_database_rejects_invalid_hierarchy_even_outside_service(client: TestClient) -> None:
    access = _register(client)
    me = client.get("/api/v1/me", headers=_auth(access))
    owner_id = UUID(me.json()["id"])

    engine = create_engine(_database_url())
    with pytest.raises(DBAPIError) as caught, engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO work_items (
                    id, owner_id, kind, parent_id, name, status, position,
                    created_at, updated_at, version
                ) VALUES (
                    :id, :owner_id, 'sprint', NULL, 'Invalid sprint', 'draft', 1024,
                    now(), now(), 1
                )
                """
            ),
            {"id": uuid4(), "owner_id": owner_id},
        )
    engine.dispose()
    assert "sprint must have a project parent" in str(caught.value)


def test_cursor_pagination_and_work_type_delete_set_null(client: TestClient) -> None:
    access = _register(client)
    custom = client.post(
        "/api/v1/work-types",
        headers=_auth(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "slug": "custom_focus",
            "displayName": "Custom Focus",
            "characteristics": {
                "cognitiveDemand": "medium",
                "interruptionSensitivity": "medium",
                "continuityNeed": "medium",
                "repetitiveness": "medium",
                "physicality": "sedentary",
                "learningMode": "none",
            },
        },
    )
    assert custom.status_code == 201
    typed = _post_work_item(
        client,
        access,
        {
            "kind": "chore",
            "name": "Typed",
            "workTypeId": custom.json()["id"],
        },
    )
    _post_work_item(client, access, {"kind": "chore", "name": "Second"})
    _post_work_item(client, access, {"kind": "chore", "name": "Third"})

    first_page = client.get("/api/v1/work-items?limit=2", headers=_auth(access))
    assert first_page.status_code == 200
    assert first_page.json()["page"]["hasMore"] is True
    cursor = first_page.json()["page"]["nextCursor"]
    second_page = client.get(
        f"/api/v1/work-items?limit=2&cursor={cursor}",
        headers=_auth(access),
    )
    assert second_page.status_code == 200
    first_ids = {item["id"] for item in first_page.json()["items"]}
    second_ids = {item["id"] for item in second_page.json()["items"]}
    assert first_ids.isdisjoint(second_ids)

    removed = client.delete(
        f"/api/v1/work-types/{custom.json()['id']}",
        headers=_auth(access, **{"If-Match": custom.headers["etag"]}),
    )
    assert removed.status_code == 204
    refreshed = client.get(
        f"/api/v1/work-items/{typed.json()['id']}",
        headers=_auth(access),
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["workTypeId"] is None
