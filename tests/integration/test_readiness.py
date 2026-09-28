import os

import pytest
from fastapi.testclient import TestClient

from taskiller.core.config import Settings
from taskiller.main import create_app

pytestmark = pytest.mark.integration


def test_readiness_against_postgres() -> None:
    database_url = os.getenv("TASKILLER_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TASKILLER_TEST_DATABASE_URL is not configured")

    settings = Settings(_env_file=None, env="test", database_url=database_url)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
