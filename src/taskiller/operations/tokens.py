from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from uuid import UUID

from taskiller.core.config import Settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_export_download_token(
    export_id: UUID, user_id: UUID, expires_at: datetime, settings: Settings
) -> str:
    payload = f"{export_id}.{user_id}.{int(expires_at.timestamp())}"
    signature = hmac.new(
        settings.token_hash_secret.encode(), payload.encode(), hashlib.sha256
    ).digest()
    return f"{payload}.{_b64(signature)}"


def verify_export_download_token(
    token: str, export_id: UUID, user_id: UUID, now: datetime, settings: Settings
) -> bool:
    parts = token.split(".")
    if len(parts) != 4:
        return False
    export_text, user_text, expiry_text, signature = parts
    if export_text != str(export_id) or user_text != str(user_id):
        return False
    try:
        expiry = int(expiry_text)
    except ValueError:
        return False
    if expiry <= int(now.timestamp()):
        return False
    payload = f"{export_text}.{user_text}.{expiry_text}"
    expected = _b64(
        hmac.new(settings.token_hash_secret.encode(), payload.encode(), hashlib.sha256).digest()
    )
    return hmac.compare_digest(signature, expected)
