import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

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
            "email": "execution@example.com",
            "password": "correct-horse-battery-staple",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["accessToken"])


def _headers(access: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", **extra}


def _create_chore_and_plan(
    client: TestClient, access: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    chore = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "kind": "chore",
            "name": "Implement execution engine",
            "status": "ready",
            "estimatedEffortSeconds": 2400,
        },
    )
    assert chore.status_code == 201, chore.text
    plan = client.post(
        "/api/v1/focus-plans",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "workItemId": chore.json()["id"],
            "source": "manual",
            "name": "Execution test",
            "segments": [
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1800,
                    "optional": False,
                },
                {
                    "kind": "break",
                    "durationMode": "fixed",
                    "targetSeconds": 300,
                    "optional": True,
                },
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 600,
                    "optional": False,
                },
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    return chore.json(), plan.json()


def _start(
    client: TestClient,
    access: str,
    chore: dict[str, Any],
    plan: dict[str, Any],
) -> Response:
    return client.post(
        "/api/v1/execution-sessions",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"workItemId": chore["id"], "focusPlanId": plan["id"]},
    )


def test_start_pause_resume_advance_complete_and_review(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    started = _start(client, access, chore, plan)
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    etag = started.headers["etag"]
    assert started.json()["state"] == "running"
    assert started.json()["currentSegmentIndex"] == 0
    assert started.json()["planSnapshot"]["segments"][0]["targetSeconds"] == 1800

    initial_events = client.get(
        f"/api/v1/execution-sessions/{session_id}/events", headers=_headers(access)
    )
    assert [item["type"] for item in initial_events.json()["items"][:2]] == [
        "session_started",
        "segment_started",
    ]

    active = client.get("/api/v1/execution-sessions/active", headers=_headers(access))
    assert active.json()["session"]["id"] == session_id

    paused = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "paused"},
    )
    assert paused.status_code == 201, paused.text
    assert paused.json()["session"]["state"] == "paused"
    etag = paused.headers["etag"]

    resumed = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "resumed"},
    )
    assert resumed.status_code == 201, resumed.text
    etag = resumed.headers["etag"]

    advanced = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "segment_completed", "segmentIndex": 0},
    )
    assert advanced.status_code == 201, advanced.text
    assert advanced.json()["session"]["currentSegmentIndex"] == 1
    assert advanced.json()["session"]["currentSegmentStartedAt"] is None
    etag = advanced.headers["etag"]

    skipped = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "segment_skipped", "segmentIndex": 1},
    )
    assert skipped.status_code == 201, skipped.text
    assert skipped.json()["session"]["currentSegmentIndex"] == 2
    etag = skipped.headers["etag"]

    work_completed = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "work_item_completed"},
    )
    assert work_completed.status_code == 201, work_completed.text
    etag = work_completed.headers["etag"]
    work_item = client.get(f"/api/v1/work-items/{chore['id']}", headers=_headers(access))
    assert work_item.json()["status"] == "completed"

    completed = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": etag},
        ),
        json={"type": "session_completed"},
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["session"]["state"] == "completed"
    assert completed.json()["session"]["endedAt"] is not None

    no_active = client.get("/api/v1/execution-sessions/active", headers=_headers(access))
    assert no_active.json() == {"session": None}

    review_key = str(uuid4())
    review = client.put(
        f"/api/v1/execution-sessions/{session_id}/review",
        headers=_headers(access, **{"Idempotency-Key": review_key}),
        json={"focusScore": 4, "fatigueScore": 2, "note": "Solid session"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["focusScore"] == 4
    replay = client.put(
        f"/api/v1/execution-sessions/{session_id}/review",
        headers=_headers(access, **{"Idempotency-Key": review_key}),
        json={"focusScore": 4, "fatigueScore": 2, "note": "Solid session"},
    )
    assert replay.status_code == 200
    assert replay.json() == review.json()


def test_one_open_session_and_stale_etag_are_enforced(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    started = _start(client, access, chore, plan)
    assert started.status_code == 201

    second = _start(client, access, chore, plan)
    assert second.status_code == 409
    assert second.json()["code"] == "open_session_exists"

    session_id = started.json()["id"]
    stale_etag = started.headers["etag"]
    first = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": stale_etag},
        ),
        json={"type": "paused"},
    )
    assert first.status_code == 201

    stale = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": stale_etag},
        ),
        json={"type": "resumed"},
    )
    assert stale.status_code == 412

    abandoned = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": first.headers["etag"]},
        ),
        json={"type": "session_abandoned"},
    )
    assert abandoned.status_code == 201, abandoned.text
    assert abandoned.json()["session"]["state"] == "abandoned"

    restarted = _start(client, access, chore, plan)
    assert restarted.status_code == 201, restarted.text


def test_event_idempotency_returns_original_post_event_snapshot(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    started = _start(client, access, chore, plan)
    session_id = started.json()["id"]
    key = str(uuid4())
    paused = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": key, "If-Match": started.headers["etag"]},
        ),
        json={"type": "paused"},
    )
    assert paused.status_code == 201
    resumed = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": paused.headers["etag"]},
        ),
        json={"type": "resumed"},
    )
    assert resumed.status_code == 201

    replay = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": key, "If-Match": started.headers["etag"]},
        ),
        json={"type": "paused"},
    )
    assert replay.status_code == 201
    assert replay.json() == paused.json()

    conflict = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": key, "If-Match": resumed.headers["etag"]},
        ),
        json={"type": "session_abandoned"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_key_reused"


def test_plan_snapshot_survives_focus_plan_edits(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    plan_get = client.get(f"/api/v1/focus-plans/{plan['id']}", headers=_headers(access))
    started = _start(client, access, chore, plan)
    assert started.status_code == 201

    edited = client.patch(
        f"/api/v1/focus-plans/{plan['id']}",
        headers=_headers(access, **{"If-Match": plan_get.headers["etag"]}),
        json={
            "segments": [
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 60,
                    "optional": False,
                }
            ]
        },
    )
    assert edited.status_code == 200, edited.text

    fetched = client.get(
        f"/api/v1/execution-sessions/{started.json()['id']}", headers=_headers(access)
    )
    assert fetched.json()["planSnapshot"]["segments"][0]["targetSeconds"] == 1800


def test_required_segment_cannot_be_skipped(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    started = _start(client, access, chore, plan)
    response = client.post(
        f"/api/v1/execution-sessions/{started.json()['id']}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": started.headers["etag"]},
        ),
        json={"type": "segment_skipped", "segmentIndex": 0},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_session_event"


def test_database_rejects_execution_snapshot_mutation(client: TestClient) -> None:
    access = _register(client)
    chore, plan = _create_chore_and_plan(client, access)
    started = _start(client, access, chore, plan)
    assert started.status_code == 201

    engine = create_engine(_database_url())
    with pytest.raises(DBAPIError) as caught, engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE execution_sessions "
                "SET plan_snapshot_json = CAST(:snapshot AS json) "
                "WHERE id = CAST(:session_id AS uuid)"
            ),
            {"snapshot": '{"segments": []}', "session_id": started.json()["id"]},
        )
    engine.dispose()
    assert "immutable" in str(caught.value.orig)
