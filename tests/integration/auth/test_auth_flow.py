import os
from collections.abc import Iterator

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
        connection.execute(
            text(
                "TRUNCATE TABLE password_reset_tokens, email_verification_tokens, "
                "refresh_tokens, auth_sessions, user_preferences"
            )
        )
        connection.execute(text("DELETE FROM users"))
    engine.dispose()


@pytest.fixture
def client_and_mailer() -> Iterator[tuple[TestClient, MemoryEmailSender]]:
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=_database_url(),
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
    )
    mailer = MemoryEmailSender()
    with TestClient(create_app(settings, email_sender=mailer)) as client:
        yield client, mailer


def _register(client: TestClient) -> tuple[str, dict[str, object]]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "person@example.com",
            "password": "correct-horse-battery-staple",
            "displayName": "Person",
            "timezone": "UTC",
            "locale": "en",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["accessToken"], body


def test_register_profile_verification_and_etag(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, mailer = client_and_mailer
    access, body = _register(client)
    assert body["user"]["emailVerified"] is False
    assert client.cookies.get("taskiller_refresh")

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    etag = me.headers["etag"]

    updated = client.patch(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access}", "If-Match": etag},
        json={"displayName": "Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["displayName"] == "Updated"
    assert updated.headers["etag"] != etag

    stale = client.patch(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access}", "If-Match": etag},
        json={"displayName": "Stale"},
    )
    assert stale.status_code == 412

    requested = client.post(
        "/api/v1/auth/email-verification/request",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert requested.status_code == 202
    token = mailer.verification_tokens["person@example.com"]
    verified = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
    assert verified.status_code == 204
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["emailVerified"] is True


def test_refresh_rotation_reuse_revokes_device_session(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, _ = client_and_mailer
    access, _ = _register(client)
    old_refresh = client.cookies.get("taskiller_refresh")
    assert old_refresh

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["accessToken"]
    assert client.cookies.get("taskiller_refresh") != old_refresh

    client.cookies.clear()
    client.cookies.set("taskiller_refresh", old_refresh, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["code"] == "refresh_token_reuse"

    revoked = client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_access}"})
    assert revoked.status_code == 401
    after_reset = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert after_reset.status_code == 401


def test_password_reset_revokes_sessions_and_changes_password(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, mailer = client_and_mailer
    access, _ = _register(client)

    request_reset = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "person@example.com"}
    )
    assert request_reset.status_code == 202
    token = mailer.reset_tokens["person@example.com"]

    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "newPassword": "a-new-very-long-password"},
    )
    assert confirm.status_code == 204
    old_access = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert old_access.status_code == 401

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": "person@example.com", "password": "correct-horse-battery-staple"},
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": "person@example.com", "password": "a-new-very-long-password"},
    )
    assert new_login.status_code == 200


def test_device_sessions_can_be_revoked(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, _ = client_and_mailer
    access, _ = _register(client)

    sessions = client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {access}"})
    assert sessions.status_code == 200
    item = sessions.json()["items"][0]
    assert item["current"] is True

    revoked = client.delete(
        f"/api/v1/auth/sessions/{item['id']}",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert revoked.status_code == 204
    after_revoke = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert after_revoke.status_code == 401


def test_preferences_have_independent_optimistic_version(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, _ = client_and_mailer
    access, _ = _register(client)
    headers = {"Authorization": f"Bearer {access}"}

    response = client.get("/api/v1/me/preferences", headers=headers)
    assert response.status_code == 200
    etag = response.headers["etag"]

    changed = client.patch(
        "/api/v1/me/preferences",
        headers={**headers, "If-Match": etag},
        json={
            "preferredStrategy": "structured",
            "preferredWorkBlockMinSeconds": 1800,
            "preferredWorkBlockMaxSeconds": 3600,
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["preferredStrategy"] == "structured"
    assert changed.headers["etag"] != etag


def test_refresh_plaintext_is_never_persisted(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, _ = client_and_mailer
    _register(client)
    plaintext = client.cookies.get("taskiller_refresh")
    assert plaintext

    engine = create_engine(_database_url())
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM refresh_tokens")).scalar_one()
    engine.dispose()

    assert stored != plaintext
    assert len(stored) == 64
    assert plaintext not in stored


def test_password_reset_request_does_not_disclose_unknown_email(
    client_and_mailer: tuple[TestClient, MemoryEmailSender],
) -> None:
    client, mailer = client_and_mailer
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 202
    assert "missing@example.com" not in mailer.reset_tokens
