from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from taskiller.auth.email import SMTPEmailSender
from taskiller.core.config import Settings
from taskiller.core.problems import PROBLEM_CODES
from taskiller.core.runtime import request_client_ip
from taskiller.main import create_app


def _production_settings(
    *,
    cors_origins: list[str] | None = None,
    allowed_hosts: list[str] | None = None,
    database_url: str = (
        "postgresql+psycopg://user:password@ep-example-pooler.eu-central-1.aws.neon.tech/db"
    ),
) -> Settings:
    return Settings(
        _env_file=None,
        env="production",
        database_url=database_url,
        jwt_secret="j" * 64,
        token_hash_secret="t" * 64,
        email_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_from_email="Taskiller <noreply@taskiller.example>",
        cors_origins=cors_origins or ["https://taskiller.example"],
        allowed_hosts=allowed_hosts or ["api.taskiller.example"],
    )


def test_deployed_settings_reject_wildcard_cors_and_hosts() -> None:
    with pytest.raises(ValidationError):
        _production_settings(cors_origins=["*"])
    with pytest.raises(ValidationError):
        _production_settings(allowed_hosts=["*"])
    with pytest.raises(ValidationError):
        _production_settings(database_url="postgresql+psycopg://u:p@localhost/taskiller")


def test_production_requires_real_email_delivery() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            env="production",
            database_url=(
                "postgresql+psycopg://u:p@ep-example-pooler.eu-central-1.aws.neon.tech/db"
            ),
            jwt_secret="j" * 64,
            token_hash_secret="t" * 64,
            cors_origins=["https://taskiller.example"],
            allowed_hosts=["api.taskiller.example"],
        )


def test_production_app_selects_smtp_sender() -> None:
    app = create_app(_production_settings())

    assert isinstance(app.state.auth_email_sender, SMTPEmailSender)


def test_request_id_and_security_headers_are_added() -> None:
    settings = Settings(_env_file=None, env="test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "release-test-123"})
        api_response = client.get("/api/v1/not-a-route")

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "release-test-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert api_response.headers["cache-control"] == "no-store"
    assert api_response.headers["x-request-id"]


def test_unhandled_errors_return_sanitized_problem() -> None:
    app = create_app(Settings(_env_file=None, env="test"))

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/explode")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["requestId"] == response.headers["x-request-id"]
    assert "secret internal detail" not in response.text


def test_openapi_has_default_problem_contract_and_complete_catalog() -> None:
    schema = create_app(Settings(_env_file=None, env="test")).openapi()

    assert schema["components"]["schemas"]["Problem"]
    assert schema["x-taskiller-problem-codes"] == sorted(PROBLEM_CODES)
    assert schema["paths"]["/api/v1/work-items"]["get"]["responses"]["default"]["content"][
        "application/problem+json"
    ]["schema"] == {"$ref": "#/components/schemas/Problem"}


def test_koyeb_forwarded_ip_uses_certified_last_entry() -> None:
    settings = Settings(_env_file=None, env="test", trust_forwarded_for=True)
    app = FastAPI()

    @app.get("/")
    async def root(request: Request) -> dict[str, str]:
        return {"ip": request_client_ip(request, settings)}

    with TestClient(app, client=("10.0.0.5", 12345)) as client:
        response = client.get("/", headers={"X-Forwarded-For": "spoofed, 198.51.100.25"})

    assert response.json() == {"ip": "198.51.100.25"}
