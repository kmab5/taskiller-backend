import asyncio
import gzip
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from taskiller.core.config import Settings
from taskiller.db.session import Database
from taskiller.main import create_app
from taskiller.operations.models import OutboxJob
from taskiller.operations.worker import claim_job, finish_job, process_job

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
                "TRUNCATE TABLE security_events, rate_limit_buckets, outbox_jobs, "
                "account_deletion_requests, data_export_requests"
            )
        )
        connection.execute(text("DELETE FROM users"))
    engine.dispose()


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url=_database_url(),
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
        **overrides,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_settings())) as value:
        yield value


def _register(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "privacy@example.com",
            "password": "correct-horse-battery-staple",
            "displayName": "Privacy User",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["accessToken"], body["user"]["id"]


async def _process_one(settings: Settings) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as db:
            job = await claim_job(db, settings, "integration-test")
        assert job is not None
        async with database.session_factory() as db:
            current = await db.get(OutboxJob, job.id)
            assert current is not None
            await process_job(db, current, settings)
            await db.commit()
        async with database.session_factory() as db:
            await finish_job(db, job.id)
    finally:
        await database.dispose()


def test_export_worker_produces_downloadable_secret_free_archive(client: TestClient) -> None:
    access, _ = _register(client)
    headers = {
        "Authorization": f"Bearer {access}",
        "Idempotency-Key": "export-integration-0001",
    }
    created = client.post("/api/v1/me/export-requests", headers=headers)
    assert created.status_code == 202, created.text
    export_id = created.json()["requestId"]

    asyncio.run(_process_one(_settings()))

    ready = client.get(
        f"/api/v1/me/export-requests/{export_id}",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    assert ready.json()["archiveSha256"]
    download = client.get(ready.json()["downloadUrl"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/gzip"
    exported = gzip.decompress(download.content)
    assert b"password_hash" not in exported
    assert b"refresh_tokens" not in exported


def test_account_deletion_revokes_access_and_worker_hard_deletes_user() -> None:
    settings = _settings(account_deletion_grace_days=0)
    with TestClient(create_app(settings)) as client:
        access, user_id = _register(client)
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
        deleted = client.delete(
            "/api/v1/me",
            headers={
                "Authorization": f"Bearer {access}",
                "If-Match": me.headers["etag"],
            },
        )
        assert deleted.status_code == 202, deleted.text
        assert (
            client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"}).status_code
            == 401
        )

        asyncio.run(_process_one(settings))

    engine = create_engine(_database_url())
    with engine.connect() as connection:
        remaining = connection.execute(
            text("SELECT count(*) FROM users WHERE id = CAST(:id AS uuid)"),
            {"id": user_id},
        ).scalar_one()
        completed = connection.execute(
            text("SELECT status FROM account_deletion_requests WHERE user_id = CAST(:id AS uuid)"),
            {"id": user_id},
        ).scalar_one()
    engine.dispose()
    assert remaining == 0
    assert completed == "completed"


def test_login_rate_limit_survives_failed_authentication_rollbacks() -> None:
    settings = _settings(rate_limit_test_mode=True, auth_login_limit=2)
    with TestClient(create_app(settings)) as client:
        _register(client)
        payload = {"email": "privacy@example.com", "password": "wrong-password"}
        first = client.post("/api/v1/auth/login", json=payload)
        second = client.post("/api/v1/auth/login", json=payload)
        third = client.post("/api/v1/auth/login", json=payload)
        assert first.status_code == 401
        assert second.status_code == 401
        assert third.status_code == 429
        assert int(third.headers["retry-after"]) >= 1
