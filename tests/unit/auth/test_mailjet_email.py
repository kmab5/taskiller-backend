from __future__ import annotations

import base64
import json

import pytest

from taskiller.auth.email import MailjetEmailSender
from taskiller.core.config import Settings


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "Messages": [
                    {
                        "Status": "success",
                        "To": [{"Email": "person@example.com"}],
                    }
                ]
            }
        ).encode()


@pytest.mark.asyncio
async def test_mailjet_sender_uses_send_api_and_builds_verification_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    settings = Settings(
        _env_file=None,
        email_delivery_mode="mailjet",
        mailjet_api_key="public-key",
        mailjet_secret_key="secret-key",
        mailjet_from_email="taskiller.sender@gmail.com",
        mailjet_from_name="Taskiller",
        web_app_url="https://taskiller-web.vercel.app",
    )
    sender = MailjetEmailSender(settings)

    await sender.send_email_verification("person@example.com", "token value")

    request = captured["request"]
    assert request.full_url == "https://api.mailjet.com/v3.1/send"
    assert captured["timeout"] == 10.0

    headers = dict(request.header_items())
    expected_basic = base64.b64encode(b"public-key:secret-key").decode()
    assert headers["Authorization"] == f"Basic {expected_basic}"
    assert headers["Content-type"] == "application/json"

    payload = json.loads(request.data)
    message = payload["Messages"][0]
    assert message["From"] == {
        "Email": "taskiller.sender@gmail.com",
        "Name": "Taskiller",
    }
    assert message["To"] == [{"Email": "person@example.com"}]
    assert "https://taskiller-web.vercel.app/verify-email?token=token+value" in message["TextPart"]


def test_mailjet_production_settings_require_credentials() -> None:
    common = {
        "_env_file": None,
        "env": "production",
        "database_url": (
            "postgresql+psycopg://u:p@ep-example-pooler.eu-central-1.aws.neon.tech/db"
        ),
        "jwt_secret": "j" * 64,
        "token_hash_secret": "t" * 64,
        "email_delivery_mode": "mailjet",
        "web_app_url": "https://taskiller-web.vercel.app",
        "cors_origins": ["https://taskiller-web.vercel.app"],
        "allowed_hosts": ["taskiller-api.onrender.com"],
    }

    with pytest.raises(ValueError):
        Settings(**common)

    settings = Settings(
        **common,
        mailjet_api_key="public-key",
        mailjet_secret_key="secret-key",
        mailjet_from_email="taskiller.sender@gmail.com",
    )
    assert settings.email_delivery_mode.value == "mailjet"
