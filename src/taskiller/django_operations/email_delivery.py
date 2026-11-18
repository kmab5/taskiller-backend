from __future__ import annotations

import hmac
from uuid import UUID

from asgiref.sync import async_to_sync

from taskiller.auth.security import derive_auth_email_token, hash_opaque_token
from taskiller.core.time import utc_now
from taskiller.django_api.runtime import auth_email_sender, taskiller_settings
from taskiller.django_domain.models import EmailVerificationToken, PasswordResetToken, TaskillerUser


def deliver_auth_email(payload: dict) -> None:
    """Deliver a queued credential; provider errors propagate for worker retry."""
    if set(payload) != {"tokenId", "userId", "kind"}:
        raise ValueError("Invalid auth email payload")
    kind = payload["kind"]
    if kind not in {"email_verification", "password_reset"}:
        raise ValueError("Unsupported auth email kind")
    token_id, user_id = UUID(payload["tokenId"]), UUID(payload["userId"])
    model = EmailVerificationToken if kind == "email_verification" else PasswordResetToken
    row = model.objects.filter(id=token_id, user_id=user_id).first()
    user = TaskillerUser.objects.filter(id=user_id, is_active=True).first()
    if row is None or user is None or row.consumed_at is not None or row.expires_at <= utc_now():
        return
    if kind == "email_verification" and user.email_verified_at is not None:
        return
    settings = taskiller_settings()
    plain = derive_auth_email_token(token_id, kind, settings)
    if not hmac.compare_digest(hash_opaque_token(plain, settings), row.token_hash):
        raise RuntimeError("Auth email credential cannot be reconstructed")
    sender = auth_email_sender()
    send = (
        sender.send_email_verification
        if kind == "email_verification"
        else sender.send_password_reset
    )
    async_to_sync(send)(user.email, plain)
