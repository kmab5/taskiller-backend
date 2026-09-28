from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError

from taskiller.core.config import Settings

try:  # Production path. The fallback keeps local source inspection/test tooling usable.
    from pwdlib import PasswordHash
except ImportError:  # pragma: no cover - exercised only when dependency installation is unavailable
    PasswordHash = None  # type: ignore[assignment,misc]


class PasswordHasher:
    def __init__(self) -> None:
        if PasswordHash is not None:
            self._pwdlib = PasswordHash.recommended()
            self._argon2 = None
        else:  # pragma: no cover - dependency fallback for constrained/offline environments
            from argon2 import PasswordHasher as Argon2PasswordHasher

            self._pwdlib = None
            self._argon2 = Argon2PasswordHasher()

    def hash(self, password: str) -> str:
        if self._pwdlib is not None:
            return self._pwdlib.hash(password)
        assert self._argon2 is not None
        return self._argon2.hash(password)

    def verify(self, password: str, encoded: str) -> bool:
        if self._pwdlib is not None:
            try:
                return bool(self._pwdlib.verify(password, encoded))
            except Exception:
                return False
        assert self._argon2 is not None
        try:
            return bool(self._argon2.verify(encoded, password))
        except Exception:
            return False


password_hasher = PasswordHasher()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def generate_opaque_token() -> str:
    # 384 bits of entropy before URL-safe encoding.
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str, settings: Settings) -> str:
    return hmac.new(
        settings.token_hash_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    jti: UUID
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    user_id: UUID,
    session_id: UUID,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    expires_at = issued_at + timedelta(seconds=settings.access_token_ttl_seconds)
    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": str(uuid4()),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
    }
    encoded = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    return encoded, expires_at


def decode_access_token(token: str, settings: Settings) -> AccessClaims | None:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"require": ["sub", "sid", "jti", "iat", "nbf", "exp", "iss", "aud"]},
        )
        user_id = UUID(str(claims["sub"]))
        session_id = UUID(str(claims["sid"]))
        jti = UUID(str(claims["jti"]))
        issued_at = datetime.fromtimestamp(float(claims["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(float(claims["exp"]), tz=UTC)
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        return None
    return AccessClaims(
        user_id=user_id,
        session_id=session_id,
        jti=jti,
        issued_at=issued_at,
        expires_at=expires_at,
    )
