from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import UUID

from django.db import connection, transaction
from rest_framework.request import Request

from taskiller.core.config import Environment
from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import RateLimitBucket, SecurityEvent

logger = logging.getLogger(__name__)


def _subject_hash(value: str) -> str:
    settings = taskiller_settings()
    return hmac.new(
        settings.token_hash_secret.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def client_ip(request: Request) -> str:
    settings = taskiller_settings()
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",", 1)[0].strip()
            if candidate:
                return candidate[:100]
    return str(request.META.get("REMOTE_ADDR") or "unknown")[:100]


def request_subject(request: Request, extra: str = "") -> str:
    return f"{client_ip(request)}|{extra.casefold().strip()}"


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> None:
    settings = taskiller_settings()
    if settings.env is Environment.TEST and not settings.rate_limit_test_mode:
        return

    digest = _subject_hash(subject)
    now = utc_now()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rate_limit_buckets
                    (scope, subject_hash, window_started_at, count, updated_at)
                VALUES (%s, %s, %s, 0, %s)
                ON CONFLICT (scope, subject_hash) DO NOTHING
                """,
                [scope, digest, now, now],
            )

        row = RateLimitBucket.objects.select_for_update().get(
            scope=scope,
            subject_hash=digest,
        )
        elapsed = (now - row.window_started_at).total_seconds()
        if elapsed >= window_seconds:
            row.window_started_at = now
            row.count = 0
            elapsed = 0
        row.count += 1
        row.updated_at = now
        row.save(
            update_fields=[
                "window_started_at",
                "count",
                "updated_at",
            ]
        )
        retry_after = max(1, int(window_seconds - elapsed))
        exceeded = row.count > limit

    if exceeded:
        raise TaskillerAPIError(
            429,
            "rate_limit_exceeded",
            "Too many requests",
            "Too many attempts were made for this operation. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def record_security_event(
    request: Request,
    *,
    event_type: str,
    user_id: UUID | None,
    metadata: dict[str, object] | None = None,
) -> None:
    try:
        SecurityEvent.objects.create(
            user_id=user_id,
            event_type=event_type,
            subject_hash=_subject_hash(client_ip(request)),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
            metadata_json=metadata or {},
            created_at=utc_now(),
        )
    except Exception:
        logger.exception("security audit event could not be persisted")
