from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import connection

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_domain.models import IdempotencyRecord


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    response_status: int
    response_body: dict[str, Any]
    resource_id: UUID | None


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def claim_idempotency(
    *,
    owner_id: UUID,
    scope: str,
    key: str,
    request_payload: dict[str, Any],
    ttl_hours: int,
) -> IdempotencyReplay | None:
    now = utc_now()
    digest = _request_hash(request_payload)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO idempotency_records
                (
                    owner_id,
                    scope,
                    idempotency_key,
                    request_hash,
                    response_status,
                    response_body_json,
                    resource_id,
                    created_at,
                    expires_at
                )
            VALUES (%s, %s, %s, %s, NULL, NULL, NULL, %s, %s)
            ON CONFLICT (owner_id, scope, idempotency_key) DO NOTHING
            """,
            [
                owner_id,
                scope,
                key,
                digest,
                now,
                now + timedelta(hours=ttl_hours),
            ],
        )

    record = IdempotencyRecord.objects.select_for_update().get(
        owner_id=owner_id,
        scope=scope,
        idempotency_key=key,
    )

    if record.expires_at <= now:
        record.request_hash = digest
        record.response_status = None
        record.response_body_json = None
        record.resource_id = None
        record.created_at = now
        record.expires_at = now + timedelta(hours=ttl_hours)
        record.save()
        return None

    if record.request_hash != digest:
        raise TaskillerAPIError(
            409,
            "idempotency_key_reused",
            "Idempotency key reused",
            "The same Idempotency-Key was already used with a different request.",
        )

    if record.response_status is not None and record.response_body_json is not None:
        return IdempotencyReplay(
            response_status=record.response_status,
            response_body=record.response_body_json,
            resource_id=record.resource_id,
        )
    return None


def complete_idempotency(
    *,
    owner_id: UUID,
    scope: str,
    key: str,
    response_status: int,
    response_body: dict[str, Any],
    resource_id: UUID | None,
) -> None:
    record = IdempotencyRecord.objects.get(
        owner_id=owner_id,
        scope=scope,
        idempotency_key=key,
    )
    record.response_status = response_status
    record.response_body_json = response_body
    record.resource_id = resource_id
    record.save(
        update_fields=[
            "response_status",
            "response_body_json",
            "resource_id",
        ]
    )
