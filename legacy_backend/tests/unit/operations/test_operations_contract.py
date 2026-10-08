from datetime import UTC, datetime, timedelta
from uuid import uuid4

from taskiller.core.config import Settings
from taskiller.main import create_app
from taskiller.operations.tokens import (
    create_export_download_token,
    verify_export_download_token,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        jwt_secret="test-jwt-secret-" + "x" * 48,
        token_hash_secret="test-token-secret-" + "y" * 48,
    )


def test_openapi_exposes_round_7_privacy_contract() -> None:
    schema = create_app(_settings()).openapi()
    expected = {
        ("/api/v1/me/export-requests", "post"): "requestDataExport",
        ("/api/v1/me/export-requests/{exportRequestId}", "get"): "getDataExportRequest",
        ("/api/v1/exports/{exportRequestId}/download", "get"): "downloadDataExport",
        ("/api/v1/me", "delete"): "requestAccountDeletion",
    }
    for (path, method), operation_id in expected.items():
        assert schema["paths"][path][method]["operationId"] == operation_id


def test_export_download_token_is_bound_to_export_user_and_expiry() -> None:
    settings = _settings()
    export_id = uuid4()
    user_id = uuid4()
    now = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)
    token = create_export_download_token(
        export_id,
        user_id,
        now + timedelta(minutes=10),
        settings,
    )
    assert verify_export_download_token(token, export_id, user_id, now, settings)
    assert not verify_export_download_token(token, uuid4(), user_id, now, settings)
    assert not verify_export_download_token(token, export_id, uuid4(), now, settings)
    assert not verify_export_download_token(
        token,
        export_id,
        user_id,
        now + timedelta(minutes=11),
        settings,
    )


def test_round_7_config_defaults_are_bounded() -> None:
    settings = _settings()
    assert 0 <= settings.account_deletion_grace_days <= 30
    assert 1 <= settings.export_ttl_hours <= 168
    assert 10 <= settings.outbox_lease_seconds <= 3600
    assert settings.outbox_max_attempts >= 1
