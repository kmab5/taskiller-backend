from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.integration
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "openapi" / "current.json").read_text(encoding="utf-8")
)


def test_authentication_response_matches_client_contract():
    response = Client().post(
        "/api/v1/auth/register",
        {"email": f"contract-{uuid4().hex}@example.com", "password": "Contract-password-123"},
        content_type="application/json",
    )
    assert response.status_code == 201
    schema = CONTRACT["paths"]["/api/v1/auth/register"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]
    Draft202012Validator({**schema, "components": CONTRACT["components"]}).validate(response.json())


def test_portable_import_declares_required_idempotency_header():
    parameters = CONTRACT["paths"]["/api/v1/portable-work/import"]["post"].get("parameters", [])
    header = next((item for item in parameters if item.get("name") == "Idempotency-Key"), None)
    assert header is not None
    assert header["required"] is True
    assert header["schema"]["minLength"] == 8
    assert header["schema"]["maxLength"] == 200
