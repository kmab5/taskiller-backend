import pytest
from pydantic import ValidationError

from taskiller.auth.schemas import RegisterRequest
from taskiller.core.config import Settings
from taskiller.main import create_app
from taskiller.users.schemas import UpdatePreferencesRequest


def test_round_two_paths_are_in_openapi() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    expected = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/sessions",
        "/api/v1/auth/sessions/{sessionId}",
        "/api/v1/auth/email-verification/request",
        "/api/v1/auth/email-verification/confirm",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/me",
        "/api/v1/me/preferences",
    }
    assert expected <= set(paths)


def test_register_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="person@example.com", password="short")


def test_preferences_reject_inverted_block_range() -> None:
    with pytest.raises(ValidationError):
        UpdatePreferencesRequest(
            preferredWorkBlockMinSeconds=3600,
            preferredWorkBlockMaxSeconds=1800,
        )


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="production")


def test_round_two_operation_ids_are_stable_for_client_generation() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    assert paths["/api/v1/auth/register"]["post"]["operationId"] == "register"
    assert paths["/api/v1/auth/refresh"]["post"]["operationId"] == "refreshAccessToken"
    assert paths["/api/v1/auth/sessions/{sessionId}"]["delete"]["operationId"] == (
        "revokeAuthSession"
    )
    assert paths["/api/v1/me"]["get"]["operationId"] == "getMe"
    assert paths["/api/v1/me/preferences"]["patch"]["operationId"] == "updatePreferences"


def test_refresh_contract_documents_cookie_input_and_rotation_output() -> None:
    operation = create_app(Settings(_env_file=None)).openapi()["paths"][
        "/api/v1/auth/refresh"
    ]["post"]
    cookie = next(item for item in operation["parameters"] if item["in"] == "cookie")

    assert cookie["name"] == "taskiller_refresh"
    assert "Set-Cookie" in operation["responses"]["200"]["headers"]
