import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import IdempotencyRecord


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


async def claim_idempotency(
    db: AsyncSession,
    *,
    owner_id: UUID,
    scope: str,
    key: str,
    request_payload: dict[str, Any],
    ttl_hours: int,
) -> IdempotencyReplay | None:
    now = utc_now()
    digest = _request_hash(request_payload)
    await db.execute(
        insert(IdempotencyRecord)
        .values(
            owner_id=owner_id,
            scope=scope,
            idempotency_key=key,
            request_hash=digest,
            response_status=None,
            response_body_json=None,
            resource_id=None,
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
        .on_conflict_do_nothing(
            index_elements=["owner_id", "scope", "idempotency_key"],
        )
    )
    record = (
        await db.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotency_key == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if record.expires_at <= now:
        record.request_hash = digest
        record.response_status = None
        record.response_body_json = None
        record.resource_id = None
        record.created_at = now
        record.expires_at = now + timedelta(hours=ttl_hours)
        return None

    if record.request_hash != digest:
        await db.rollback()
        raise ApiError(
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


async def complete_idempotency(
    db: AsyncSession,
    *,
    owner_id: UUID,
    scope: str,
    key: str,
    response_status: int,
    response_body: dict[str, Any],
    resource_id: UUID | None,
) -> None:
    record = (
        await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotency_key == key,
            )
        )
    ).scalar_one()
    record.response_status = response_status
    record.response_body_json = response_body
    record.resource_id = resource_id
