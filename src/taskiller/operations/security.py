from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from taskiller.core.config import Environment, Settings
from taskiller.core.problems import ApiError
from taskiller.core.runtime import request_client_ip
from taskiller.core.time import utc_now
from taskiller.operations.models import RateLimitBucket, SecurityEvent

logger = logging.getLogger(__name__)


def _subject_hash(value: str, settings: Settings) -> str:
    return hmac.new(
        settings.token_hash_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def request_subject(request: Request, extra: str = "") -> str:
    settings: Settings = request.app.state.settings
    host = request_client_ip(request, settings)
    return f"{host}|{extra.casefold().strip()}"


async def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> None:
    settings: Settings = request.app.state.settings
    if settings.env is Environment.TEST and not settings.rate_limit_test_mode:
        return
    digest = _subject_hash(subject, settings)
    now = utc_now()
    async with request.app.state.database.session_factory() as db:
        await db.execute(
            insert(RateLimitBucket)
            .values(
                scope=scope,
                subject_hash=digest,
                window_started_at=now,
                count=0,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["scope", "subject_hash"])
        )
        row = (
            await db.execute(
                select(RateLimitBucket)
                .where(
                    RateLimitBucket.scope == scope,
                    RateLimitBucket.subject_hash == digest,
                )
                .with_for_update()
            )
        ).scalar_one()
        elapsed = (now - row.window_started_at).total_seconds()
        if elapsed >= window_seconds:
            row.window_started_at = now
            row.count = 0
            elapsed = 0
        row.count += 1
        row.updated_at = now
        retry_after = max(1, int(window_seconds - elapsed))
        exceeded = row.count > limit
        await db.commit()
    if exceeded:
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Too many requests",
            "Too many attempts were made for this operation. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def record_security_event(
    request: Request,
    *,
    event_type: str,
    user_id: UUID | None,
    metadata: dict[str, object] | None = None,
) -> None:
    settings: Settings = request.app.state.settings
    host = request_client_ip(request, settings)
    user_agent = (request.headers.get("user-agent") or "")[:300] or None
    try:
        async with request.app.state.database.session_factory() as db:
            db.add(
                SecurityEvent(
                    user_id=user_id,
                    event_type=event_type,
                    subject_hash=_subject_hash(host, settings),
                    user_agent=user_agent,
                    metadata_json=metadata or {},
                    created_at=utc_now(),
                )
            )
            await db.commit()
    except Exception:
        logger.exception("security audit event could not be persisted")

