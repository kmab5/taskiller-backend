from __future__ import annotations

import argparse
import asyncio
import logging
import socket
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.core.config import Settings, get_settings
from taskiller.core.time import utc_now
from taskiller.db.models import (
    EmailVerificationToken,
    IdempotencyRecord,
    PasswordResetToken,
    RefreshToken,
)
from taskiller.db.session import Database
from taskiller.operations.models import (
    AccountDeletionRequest,
    DataExportRequest,
    OutboxJob,
    RateLimitBucket,
    SecurityEvent,
)
from taskiller.operations.service import build_export_archive, hard_delete_account

logger = logging.getLogger(__name__)


async def recover_expired_leases(db: AsyncSession) -> int:
    now = utc_now()
    result = await db.execute(
        update(OutboxJob)
        .where(OutboxJob.status == "running", OutboxJob.lease_expires_at <= now)
        .values(
            status="queued",
            locked_at=None,
            locked_by=None,
            lease_expires_at=None,
            available_at=now,
            updated_at=now,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def ensure_retention_job(db: AsyncSession, settings: Settings) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('taskiller-retention-scheduler'))")
    )
    existing = (
        await db.execute(
            select(OutboxJob.id).where(
                OutboxJob.job_type == "retention",
                OutboxJob.status.in_(["queued", "running"]),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        now = utc_now()
        db.add(
            OutboxJob(
                job_type="retention",
                payload_json={},
                status="queued",
                available_at=now,
                locked_at=None,
                locked_by=None,
                lease_expires_at=None,
                attempts=0,
                max_attempts=settings.outbox_max_attempts,
                last_error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
        )
    await db.commit()


async def claim_job(db: AsyncSession, settings: Settings, worker_id: str) -> OutboxJob | None:
    now = utc_now()
    job = (
        await db.execute(
            select(OutboxJob)
            .where(OutboxJob.status == "queued", OutboxJob.available_at <= now)
            .order_by(OutboxJob.available_at, OutboxJob.created_at, OutboxJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        await db.rollback()
        return None
    job.status = "running"
    job.locked_at = now
    job.locked_by = worker_id
    job.lease_expires_at = now + timedelta(seconds=settings.outbox_lease_seconds)
    job.attempts += 1
    job.updated_at = now
    await db.commit()
    return job


async def _run_retention(db: AsyncSession, settings: Settings) -> None:
    now = utc_now()
    await db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= now))
    await db.execute(delete(RefreshToken).where(RefreshToken.expires_at <= now))
    await db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.expires_at <= now))
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at <= now))
    await db.execute(
        delete(RateLimitBucket).where(
            RateLimitBucket.updated_at
            <= now - timedelta(seconds=settings.rate_limit_bucket_retention_seconds)
        )
    )
    await db.execute(
        update(DataExportRequest)
        .where(DataExportRequest.expires_at.is_not(None), DataExportRequest.expires_at <= now)
        .values(archive_bytes=None, archive_size_bytes=None)
    )
    await db.execute(text("SET LOCAL taskiller.retention = 'on'"))
    await db.execute(
        delete(SecurityEvent).where(
            SecurityEvent.created_at
            <= now - timedelta(days=settings.security_event_retention_days)
        )
    )
    await db.execute(
        delete(AccountDeletionRequest).where(
            AccountDeletionRequest.status == "completed",
            AccountDeletionRequest.completed_at
            <= now - timedelta(days=settings.deletion_tombstone_retention_days),
        )
    )
    await db.execute(
        delete(OutboxJob).where(
            OutboxJob.status.in_(["succeeded", "dead"]),
            OutboxJob.completed_at
            <= now - timedelta(days=settings.outbox_history_retention_days),
        )
    )


async def process_job(db: AsyncSession, job: OutboxJob, settings: Settings) -> None:
    if job.job_type == "data_export":
        export_id = UUID(str(job.payload_json["exportRequestId"]))
        export = (
            await db.execute(
                select(DataExportRequest)
                .where(DataExportRequest.id == export_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if export is None:
            return
        export.status = "processing"
        export.started_at = export.started_at or utc_now()
        await build_export_archive(db, export, settings)
        return
    if job.job_type == "account_delete":
        request_id = UUID(str(job.payload_json["requestId"]))
        deletion = (
            await db.execute(
                select(AccountDeletionRequest)
                .where(AccountDeletionRequest.id == request_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if deletion is None or deletion.status == "completed":
            return
        await hard_delete_account(db, deletion)
        return
    if job.job_type == "retention":
        await _run_retention(db, settings)
        now = utc_now()
        db.add(
            OutboxJob(
                job_type="retention",
                payload_json={},
                status="queued",
                available_at=now + timedelta(hours=24),
                locked_at=None,
                locked_by=None,
                lease_expires_at=None,
                attempts=0,
                max_attempts=settings.outbox_max_attempts,
                last_error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
        )
        return
    raise RuntimeError(f"unsupported outbox job type: {job.job_type}")


async def finish_job(db: AsyncSession, job_id: UUID) -> None:
    job = (
        await db.execute(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update())
    ).scalar_one()
    now = utc_now()
    job.status = "succeeded"
    job.completed_at = now
    job.updated_at = now
    job.locked_at = None
    job.locked_by = None
    job.lease_expires_at = None
    job.last_error = None
    await db.commit()


async def fail_job(db: AsyncSession, job_id: UUID, settings: Settings, error: Exception) -> None:
    job = (
        await db.execute(select(OutboxJob).where(OutboxJob.id == job_id).with_for_update())
    ).scalar_one()
    now = utc_now()
    terminal = job.attempts >= job.max_attempts
    job.status = "dead" if terminal else "queued"
    job.available_at = now + timedelta(seconds=min(300, 2 ** max(0, job.attempts - 1) * 5))
    job.completed_at = now if terminal else None
    job.updated_at = now
    job.locked_at = None
    job.locked_by = None
    job.lease_expires_at = None
    job.last_error = f"{type(error).__name__}: {error}"[:2000]
    if job.job_type == "data_export" and terminal:
        export_id = UUID(str(job.payload_json["exportRequestId"]))
        await db.execute(
            update(DataExportRequest)
            .where(DataExportRequest.id == export_id)
            .values(status="failed", failure_code="export_generation_failed")
        )
    if job.job_type == "account_delete" and terminal:
        request_id = UUID(str(job.payload_json["requestId"]))
        await db.execute(
            update(AccountDeletionRequest)
            .where(AccountDeletionRequest.id == request_id)
            .values(status="failed", failure_code="account_deletion_failed")
        )
    await db.commit()


async def run_worker_loop(
    database: Database,
    settings: Settings,
    *,
    stop_event: asyncio.Event | None = None,
    once: bool = False,
) -> None:
    worker_id = f"{socket.gethostname()}:{id(database)}"
    async with database.session_factory() as db:
        await recover_expired_leases(db)
    async with database.session_factory() as db:
        await ensure_retention_job(db, settings)
    while stop_event is None or not stop_event.is_set():
        async with database.session_factory() as db:
            job = await claim_job(db, settings, worker_id)
        if job is None:
            if once:
                return
            if stop_event is None:
                await asyncio.sleep(settings.outbox_poll_seconds)
            else:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=settings.outbox_poll_seconds
                    )
                except TimeoutError:
                    pass
            continue
        try:
            async with database.session_factory() as db:
                current = await db.get(OutboxJob, job.id)
                if current is None:
                    continue
                await process_job(db, current, settings)
                await db.commit()
            async with database.session_factory() as db:
                await finish_job(db, job.id)
        except Exception as exc:  # noqa: BLE001 - worker isolates job failures
            logger.exception("outbox job failed", extra={"job_id": str(job.id)})
            async with database.session_factory() as db:
                await fail_job(db, job.id, settings, exc)
        if once:
            return


async def run_worker(*, once: bool = False) -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        await run_worker_loop(database, settings, once=once)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Taskiller PostgreSQL outbox worker")
    parser.add_argument("--once", action="store_true", help="Process at most one available job")
    args = parser.parse_args()
    asyncio.run(run_worker(once=args.once))


if __name__ == "__main__":
    main()
