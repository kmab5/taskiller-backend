import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
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


def _headers(access: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", **extra}


def _register(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "analytics@example.com",
            "password": "correct-horse-battery-staple",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["accessToken"]), str(response.json()["user"]["id"])


def _create_chore_and_plan(
    client: TestClient, access: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    types = client.get("/api/v1/work-types", headers=_headers(access))
    programming = next(item for item in types.json()["items"] if item["slug"] == "programming")
    chore = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "kind": "chore",
            "name": "Historical analytics task",
            "status": "ready",
            "workTypeId": programming["id"],
            "estimatedEffortSeconds": 1800,
            "plannedStartAt": "2026-09-20T09:55:00Z",
        },
    )
    assert chore.status_code == 201, chore.text
    plan = client.post(
        "/api/v1/focus-plans",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "workItemId": chore.json()["id"],
            "source": "manual",
            "name": "Analytics plan",
            "segments": [
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1800,
                    "linkedWorkItemId": chore.json()["id"],
                    "optional": False,
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    return chore.json(), plan.json(), programming


def _seed_historical_session(
    user_id: str,
    chore: dict[str, Any],
    plan: dict[str, Any],
    work_type: dict[str, Any],
    *,
    day_offset: int = 0,
) -> str:
    session_id = str(uuid4())
    started = datetime(2026, 9, 20, 10, 0, tzinfo=UTC) + timedelta(days=day_offset)
    ended = started + timedelta(minutes=35, seconds=2)
    plan_snapshot = {
        "strategy": None,
        "segments": [
            {
                "kind": "work",
                "durationMode": "fixed",
                "targetSeconds": 1800,
                "minSeconds": None,
                "maxSeconds": None,
                "linkedWorkItemId": chore["id"],
                "optional": False,
                "label": None,
                "instructions": None,
            }
        ],
    }
    context = {
        "capturedAt": started.isoformat(),
        "target": {
            "id": chore["id"],
            "kind": "chore",
            "parentId": None,
            "ancestorIds": [],
            "workTypeId": work_type["id"],
            "workTypeSlug": "programming",
            "estimatedEffortSeconds": 1800,
            "plannedStartAt": (started - timedelta(minutes=5)).isoformat(),
        },
        "linkedWorkItems": {},
    }
    events = [
        ("session_started", started, None, {}),
        ("segment_started", started + timedelta(milliseconds=100), 0, {}),
        ("paused", started + timedelta(minutes=20, milliseconds=100), None, {}),
        ("resumed", started + timedelta(minutes=25, milliseconds=100), None, {}),
        (
            "segment_completed",
            started + timedelta(minutes=35, milliseconds=100),
            0,
            {},
        ),
        ("work_item_completed", started + timedelta(minutes=35, seconds=1), None, {}),
        ("session_completed", ended, None, {}),
    ]
    engine = create_engine(_database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO execution_sessions "
                "(id, owner_id, work_item_id, focus_plan_id, recommendation_id, state, "
                "current_segment_index, session_started_at, current_segment_started_at, "
                "paused_at, ended_at, plan_snapshot_json, recommendation_snapshot_json, "
                "work_context_snapshot_json, created_at, updated_at, version) "
                "VALUES (CAST(:id AS uuid), CAST(:owner AS uuid), CAST(:work AS uuid), "
                "CAST(:plan AS uuid), NULL, 'completed', 1, :started, NULL, NULL, :ended, "
                "CAST(:plan_snapshot AS json), NULL, CAST(:context AS json), :started, :ended, 1)"
            ),
            {
                "id": session_id,
                "owner": user_id,
                "work": chore["id"],
                "plan": plan["id"],
                "started": started,
                "ended": ended,
                "plan_snapshot": json.dumps(plan_snapshot),
                "context": json.dumps(context),
            },
        )
        for event_type, occurred, index, payload in events:
            connection.execute(
                text(
                    "INSERT INTO session_events "
                    "(id, session_id, owner_id, type, occurred_at, client_occurred_at, "
                    "segment_index, idempotency_key, request_hash, payload_json, "
                    "result_session_snapshot_json, created_at) "
                    "VALUES (CAST(:id AS uuid), CAST(:session AS uuid), CAST(:owner AS uuid), "
                    ":type, :occurred, NULL, :segment_index, :key, :hash, "
                    "CAST(:payload AS json), CAST('{}' AS json), :occurred)"
                ),
                {
                    "id": str(uuid4()),
                    "session": session_id,
                    "owner": user_id,
                    "type": event_type,
                    "occurred": occurred,
                    "segment_index": index,
                    "key": str(uuid4()),
                    "hash": "a" * 64,
                    "payload": json.dumps(payload),
                },
            )
        connection.execute(
            text(
                "INSERT INTO session_reviews "
                "(session_id, owner_id, focus_score, fatigue_score, difficulty_score, "
                "satisfaction_score, note, created_at, updated_at, version) "
                "VALUES (CAST(:session AS uuid), CAST(:owner AS uuid), 4, 2, 3, 4, NULL, "
                ":ended, :ended, 1)"
            ),
            {"session": session_id, "owner": user_id, "ended": ended},
        )
    engine.dispose()
    return session_id


def test_analytics_endpoints_derive_historical_execution(client: TestClient) -> None:
    access, user_id = _register(client)
    chore, plan, work_type = _create_chore_and_plan(client, access)
    _seed_historical_session(user_id, chore, plan, work_type)
    params = {"from": "2026-09-20T00:00:00Z", "to": "2026-09-21T00:00:00Z"}

    summary = client.get("/api/v1/analytics/summary", headers=_headers(access), params=params)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["activeWorkSeconds"] == 1800
    assert body["pausedSeconds"] == 300
    assert body["sessionsCompleted"] == 1
    assert body["choresCompleted"] == 1
    assert body["medianEstimateErrorSeconds"] == 0
    assert body["medianStartDelaySeconds"] == 300
    assert body["requiredSegmentsCompleted"] == 1
    assert body["planAdherenceRate"] == 1.0

    work_types = client.get(
        "/api/v1/analytics/work-types", headers=_headers(access), params=params
    )
    programming = next(
        item for item in work_types.json()["items"] if item["workTypeSlug"] == "programming"
    )
    assert programming["activeWorkSeconds"] == 1800
    assert programming["medianFocusScore"] == 4.0

    item = client.get(
        f"/api/v1/analytics/work-items/{chore['id']}",
        headers=_headers(access),
        params=params,
    )
    assert item.status_code == 200, item.text
    assert item.json()["activeWorkSeconds"] == 1800
    assert item.json()["estimateErrorSeconds"] == 0

    series = client.get(
        "/api/v1/analytics/timeseries",
        headers=_headers(access),
        params={**params, "bucket": "day"},
    )
    assert series.status_code == 200, series.text
    assert series.json()["points"][0]["activeWorkSeconds"] == 1800
    assert series.json()["points"][0]["pausedSeconds"] == 300

    patterns = client.get(
        "/api/v1/analytics/focus-patterns", headers=_headers(access), params=params
    )
    assert patterns.status_code == 200, patterns.text
    programming_pattern = next(
        item for item in patterns.json()["items"] if item["workTypeSlug"] == "programming"
    )
    assert programming_pattern["sampleSize"] == 1
    assert programming_pattern["medianUninterruptedWorkSeconds"] == 900
    assert not programming_pattern["recommendationPersonalizationEligible"]


def test_personal_history_marks_recommendation_history_informed(client: TestClient) -> None:
    access, user_id = _register(client)
    chore, plan, work_type = _create_chore_and_plan(client, access)
    for offset in range(5):
        _seed_historical_session(
            user_id, chore, plan, work_type, day_offset=offset
        )

    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "workItemId": chore["id"],
            "preferredStrategy": "structured",
        },
    )
    assert recommendation.status_code == 201, recommendation.text
    body = recommendation.json()
    assert body["engineVersion"] == "focus-v1.1"
    assert body["provenance"] == "history_informed"
    assert any(
        reason["label"] == "personal_pattern"
        and reason["code"] == "PERSONAL_COMPLETED_SESSION_PATTERN"
        for reason in body["reasons"]
    )


def test_database_rejects_work_context_snapshot_mutation(client: TestClient) -> None:
    access, user_id = _register(client)
    chore, plan, work_type = _create_chore_and_plan(client, access)
    session_id = _seed_historical_session(user_id, chore, plan, work_type)

    engine = create_engine(_database_url())
    with pytest.raises(DBAPIError) as caught, engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE execution_sessions "
                "SET work_context_snapshot_json = CAST('{}' AS json), version = version + 1 "
                "WHERE id = CAST(:session_id AS uuid)"
            ),
            {"session_id": session_id},
        )
    engine.dispose()
    assert "snapshots are immutable" in str(caught.value.orig)
