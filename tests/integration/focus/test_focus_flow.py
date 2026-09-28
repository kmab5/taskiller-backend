import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

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


def _register(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "focus@example.com",
            "password": "correct-horse-battery-staple",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["accessToken"])


def _headers(access: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", **extra}


def _create_chore(client: TestClient, access: str, *, work_type_id: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "kind": "chore",
            "name": "Implement focus engine",
            "status": "ready",
            "workTypeId": work_type_id,
            "estimatedEffortSeconds": 5400,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_recommendation_is_idempotent_and_can_be_saved_as_edited_plan(client: TestClient) -> None:
    access = _register(client)
    work_types = client.get("/api/v1/work-types", headers=_headers(access)).json()["items"]
    programming = next(item for item in work_types if item["slug"] == "programming")
    chore = _create_chore(client, access, work_type_id=programming["id"])

    key = str(uuid4())
    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": key}),
        json={"workItemId": chore["id"]},
    )
    assert recommendation.status_code == 201, recommendation.text
    replay = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": key}),
        json={"workItemId": chore["id"]},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == recommendation.json()["id"]
    assert recommendation.json()["engineVersion"] == "focus-v1.0"
    assert recommendation.json()["reasons"]

    selected_segments = recommendation.json()["plan"]["segments"]
    selected_segments[0]["targetSeconds"] = 3000
    if selected_segments[0]["durationMode"] == "flexible":
        selected_segments[0]["minSeconds"] = min(selected_segments[0]["minSeconds"], 3000)
        selected_segments[0]["maxSeconds"] = max(selected_segments[0]["maxSeconds"], 3000)
    plan = client.post(
        "/api/v1/focus-plans",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "workItemId": chore["id"],
            "recommendationId": recommendation.json()["id"],
            "source": "recommendation",
            "name": "My edited plan",
            "segments": selected_segments,
        },
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["recommendationId"] == recommendation.json()["id"]
    assert plan.json()["segments"][0]["targetSeconds"] == 3000

    fetched_recommendation = client.get(
        f"/api/v1/focus-plan-recommendations/{recommendation.json()['id']}",
        headers=_headers(access),
    )
    assert fetched_recommendation.json()["plan"]["segments"][0]["targetSeconds"] != 3000


def test_focus_plan_etag_update_and_soft_delete(client: TestClient) -> None:
    access = _register(client)
    created = client.post(
        "/api/v1/focus-plans",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "source": "manual",
            "name": "Manual plan",
            "segments": [
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1800,
                    "optional": False,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    etag = created.headers["etag"]
    plan_id = created.json()["id"]

    changed = client.patch(
        f"/api/v1/focus-plans/{plan_id}",
        headers=_headers(access, **{"If-Match": etag}),
        json={"name": "Updated plan"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.headers["etag"] != etag

    stale = client.patch(
        f"/api/v1/focus-plans/{plan_id}",
        headers=_headers(access, **{"If-Match": etag}),
        json={"name": "Stale"},
    )
    assert stale.status_code == 412

    deleted = client.delete(
        f"/api/v1/focus-plans/{plan_id}",
        headers=_headers(access, **{"If-Match": changed.headers["etag"]}),
    )
    assert deleted.status_code == 204
    missing = client.get(f"/api/v1/focus-plans/{plan_id}", headers=_headers(access))
    assert missing.status_code == 404


def test_study_recommendation_contains_retrieval_segment(client: TestClient) -> None:
    access = _register(client)
    work_types = client.get("/api/v1/work-types", headers=_headers(access)).json()["items"]
    study = next(item for item in work_types if item["slug"] == "study_learning")
    chore = _create_chore(client, access, work_type_id=study["id"])

    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"workItemId": chore["id"]},
    )
    assert recommendation.status_code == 201, recommendation.text
    kinds = [segment["kind"] for segment in recommendation.json()["plan"]["segments"]]
    assert "retrieval" in kinds


def test_project_recommendation_is_rejected(client: TestClient) -> None:
    access = _register(client)
    project = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"kind": "project", "name": "Taskiller", "status": "ready"},
    )
    assert project.status_code == 201
    response = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"workItemId": project.json()["id"], "availableTimeSeconds": 3600},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "project_requires_next_action"
