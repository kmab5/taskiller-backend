from __future__ import annotations

import asyncio
import gzip
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from taskiller.auth.email import MemoryEmailSender
from taskiller.core.config import Settings
from taskiller.db.session import Database
from taskiller.main import create_app
from taskiller.operations.models import OutboxJob
from taskiller.operations.worker import claim_job, finish_job, process_job

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TASKILLER_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TASKILLER_TEST_DATABASE_URL is not configured")
    return value


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url=_database_url(),
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
    )


@pytest.fixture(autouse=True)
def clean_database() -> None:
    engine = create_engine(_database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE security_events, rate_limit_buckets, outbox_jobs, "
                "account_deletion_requests, data_export_requests"
            )
        )
        connection.execute(text("DELETE FROM users"))
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_settings(), email_sender=MemoryEmailSender())) as value:
        yield value


def _headers(access: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", **extra}


async def _process_export_job(settings: Settings) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as db:
            job = await claim_job(db, settings, "release-smoke")
        assert job is not None
        assert job.job_type == "data_export"
        async with database.session_factory() as db:
            current = await db.get(OutboxJob, job.id)
            assert current is not None
            await process_job(db, current, settings)
            await db.commit()
        async with database.session_factory() as db:
            await finish_job(db, job.id)
    finally:
        await database.dispose()


def test_v1_release_end_to_end(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "release@example.com",
            "password": "correct-horse-battery-staple",
            "displayName": "Release User",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert registered.status_code == 201, registered.text
    access = registered.json()["accessToken"]

    work_types = client.get("/api/v1/work-types", headers=_headers(access))
    assert work_types.status_code == 200
    programming = next(
        item for item in work_types.json()["items"] if item["slug"] == "programming"
    )

    project = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"kind": "project", "name": "Taskiller release", "status": "ready"},
    )
    assert project.status_code == 201, project.text

    sprint = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "kind": "sprint",
            "name": "Release sprint",
            "status": "ready",
            "parentId": project.json()["id"],
        },
    )
    assert sprint.status_code == 201, sprint.text

    chore = client.post(
        "/api/v1/work-items",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "kind": "chore",
            "name": "Ship backend",
            "status": "ready",
            "parentId": sprint.json()["id"],
            "workTypeId": programming["id"],
            "estimatedEffortSeconds": 1800,
        },
    )
    assert chore.status_code == 201, chore.text

    recommendation = client.post(
        "/api/v1/focus-plan-recommendations",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"workItemId": chore.json()["id"], "availableTimeSeconds": 1800},
    )
    assert recommendation.status_code == 201, recommendation.text

    plan = client.post(
        "/api/v1/focus-plans",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={
            "workItemId": chore.json()["id"],
            "recommendationId": recommendation.json()["id"],
            "source": "recommendation",
            "name": "Release plan",
            "segments": recommendation.json()["plan"]["segments"],
        },
    )
    assert plan.status_code == 201, plan.text

    session = client.post(
        "/api/v1/execution-sessions",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
        json={"workItemId": chore.json()["id"], "focusPlanId": plan.json()["id"]},
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    completed_work = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{"Idempotency-Key": str(uuid4()), "If-Match": session.headers["etag"]},
        ),
        json={"type": "work_item_completed"},
    )
    assert completed_work.status_code == 201, completed_work.text

    completed_session = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        headers=_headers(
            access,
            **{
                "Idempotency-Key": str(uuid4()),
                "If-Match": completed_work.headers["etag"],
            },
        ),
        json={"type": "session_completed"},
    )
    assert completed_session.status_code == 201, completed_session.text

    now = datetime.now(UTC)
    analytics = client.get(
        "/api/v1/analytics/summary",
        headers=_headers(access),
        params={
            "from": (now - timedelta(hours=1)).isoformat(),
            "to": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["sessionsCompleted"] >= 1

    export = client.post(
        "/api/v1/me/export-requests",
        headers=_headers(access, **{"Idempotency-Key": str(uuid4())}),
    )
    assert export.status_code == 202, export.text
    asyncio.run(_process_export_job(_settings()))

    ready_export = client.get(
        f"/api/v1/me/export-requests/{export.json()['requestId']}",
        headers=_headers(access),
    )
    assert ready_export.status_code == 200
    assert ready_export.json()["status"] == "ready"
    downloaded = client.get(ready_export.json()["downloadUrl"])
    assert downloaded.status_code == 200
    payload = gzip.decompress(downloaded.content)
    assert b"release@example.com" in payload
    assert b"password_hash" not in payload
