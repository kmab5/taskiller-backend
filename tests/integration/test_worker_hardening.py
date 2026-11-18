from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import models

from taskiller.core.time import utc_now
from taskiller.django_domain import models as domain
from taskiller.django_operations import worker_service as worker

pytestmark = pytest.mark.integration


def row(model, **values):
    """Fill mechanical required columns; domain relationships stay explicit below."""
    for field in model._meta.local_fields:
        if field.attname in values or field.null or field.has_default():
            continue
        if isinstance(field, models.UUIDField):
            values[field.attname] = uuid4()
        elif isinstance(field, models.DateTimeField):
            values[field.attname] = utc_now()
        elif isinstance(field, models.BooleanField):
            values[field.attname] = False
        elif isinstance(field, models.IntegerField):
            values[field.attname] = 1
        elif isinstance(field, models.JSONField):
            values[field.attname] = {}
        elif isinstance(field, (models.CharField, models.TextField)):
            values[field.attname] = uuid4().hex[: field.max_length or 32]
    return model.objects.create(**values)


def job(kind="retention", **values):
    return row(
        domain.OutboxJob,
        job_type=kind,
        status=values.pop("status", "queued"),
        payload_json=values.pop("payload_json", {}),
        available_at=utc_now(),
        attempts=values.pop("attempts", 0),
        max_attempts=values.pop("max_attempts", 2),
        **values,
    )


def test_delete_populated_account_preserves_tombstone_and_discards_email():
    user = row(domain.TaskillerUser, email=f"{uuid4()}@example.test", is_active=True)
    row(domain.UserPreferences, user_id=user.id)
    auth = row(domain.AuthSession, user_id=user.id)
    old = row(domain.RefreshToken, session_id=auth.id)
    replacement = row(domain.RefreshToken, session_id=auth.id)
    old.replaced_by = replacement
    old.save(update_fields=["replaced_by"])
    token = row(domain.EmailVerificationToken, user_id=user.id)
    row(domain.PasswordResetToken, user_id=user.id)
    custom = row(domain.WorkType, owner_id=user.id, is_system=False)
    project = row(domain.WorkItem, owner_id=user.id, kind="project", status="ready")
    sprint = row(domain.WorkItem, owner_id=user.id, kind="sprint", status="ready", parent=project)
    chore = row(
        domain.WorkItem,
        owner_id=user.id,
        kind="chore",
        status="ready",
        parent=sprint,
        work_type=custom,
    )
    recommendation = row(domain.FocusPlanRecommendation, owner_id=user.id, work_item=chore)
    plan = row(domain.FocusPlan, owner_id=user.id, work_item=chore, recommendation=recommendation)
    row(domain.FocusPlanSegment, focus_plan=plan, linked_work_item=chore, segment_index=0)
    session = row(
        domain.ExecutionSession,
        owner_id=user.id,
        work_item=chore,
        focus_plan=plan,
        recommendation=recommendation,
        state="completed",
    )
    row(domain.SessionEvent, owner_id=user.id, session=session)
    row(domain.SessionReview, owner_id=user.id, session=session)
    row(domain.DataExportRequest, user_id=user.id, status="queued")
    row(domain.IdempotencyRecord, owner_id=user.id)
    deletion = row(domain.AccountDeletionRequest, user_id=user.id, status="scheduled")
    email = job(
        "auth_email",
        payload_json={
            "tokenId": str(token.id),
            "userId": str(user.id),
            "kind": "email_verification",
        },
    )
    worker._hard_delete_account(deletion)
    assert not domain.TaskillerUser.objects.filter(id=user.id).exists()
    assert not domain.RefreshToken.objects.filter(session_id=auth.id).exists()
    assert not domain.WorkItem.objects.filter(owner_id=user.id).exists()
    deletion.refresh_from_db()
    assert deletion.status == "completed"
    worker._process_locked_job(email)


def test_recovery_exhausts_attempts_and_marks_export_failed():
    user = row(domain.TaskillerUser, email=f"{uuid4()}@example.test")
    export = row(domain.DataExportRequest, user_id=user.id, status="processing")
    expired = job(
        "data_export",
        status="running",
        attempts=2,
        payload_json={"exportRequestId": str(export.id)},
        locked_by="lost",
        lease_expires_at=utc_now() - timedelta(seconds=1),
    )
    assert worker.recover_expired_leases() >= 1
    expired.refresh_from_db()
    export.refresh_from_db()
    assert expired.status == "dead"
    assert expired.locked_by is None
    assert export.status == "failed"


def test_account_deletion_locks_sessions_before_mutating_refresh_tokens():
    from django.db import connection

    user = row(domain.TaskillerUser, email=f"{uuid4()}@example.test")
    sessions = [row(domain.AuthSession, user_id=user.id) for _ in range(2)]
    for session in sessions:
        row(domain.RefreshToken, session_id=session.id)
    deletion = row(domain.AccountDeletionRequest, user_id=user.id, status="scheduled")
    statements = []

    def record(execute, sql, params, many, context):
        statements.append(sql)
        return execute(sql, params, many, context)

    domain.TaskillerUser.objects.select_for_update().get(id=user.id)
    with connection.execute_wrapper(record):
        worker._hard_delete_account(deletion)

    session_locks = [
        index
        for index, sql in enumerate(statements)
        if 'FROM "auth_sessions"' in sql and "FOR UPDATE" in sql
    ]
    token_mutations = [
        index
        for index, sql in enumerate(statements)
        if '"refresh_tokens"' in sql and sql.startswith(("UPDATE", "DELETE"))
    ]
    assert session_locks, "Deletion must acquire session locks before refresh-token locks"
    assert token_mutations
    assert max(session_locks) < min(token_mutations)
    assert 'ORDER BY "auth_sessions"."id" ASC' in statements[session_locks[0]]


def test_retention_nulls_refresh_reference_and_has_only_one_successor():
    user = row(domain.TaskillerUser, email=f"{uuid4()}@example.test")
    auth = row(domain.AuthSession, user_id=user.id)
    expired = row(
        domain.RefreshToken, session_id=auth.id, expires_at=utc_now() - timedelta(seconds=1)
    )
    surviving = row(
        domain.RefreshToken,
        session_id=auth.id,
        replaced_by=expired,
        expires_at=utc_now() + timedelta(days=1),
    )
    current = job(status="running")
    worker._process_locked_job(current)
    worker._process_locked_job(current)
    surviving.refresh_from_db()
    assert surviving.replaced_by_id is None
    assert domain.OutboxJob.objects.filter(job_type="retention", status="queued").count() == 1


def test_reclaimed_job_rejects_stale_success_and_failure():
    current = job()
    # Exclude fixture-independent scheduling from claim selection.
    domain.OutboxJob.objects.exclude(id=current.id).update(
        available_at=utc_now() + timedelta(days=7)
    )
    job_id, first = worker.claim_job("host", with_token=True)
    domain.OutboxJob.objects.filter(id=job_id).update(
        lease_expires_at=utc_now() - timedelta(seconds=1)
    )
    worker.recover_expired_leases()
    domain.OutboxJob.objects.filter(id=job_id).update(available_at=utc_now())
    _, second = worker.claim_job("host", with_token=True)
    assert first != second
    assert worker.finish_job(job_id, claim_token=first) is False
    assert worker.fail_job(job_id, RuntimeError("stale"), claim_token=first) is False
    current.refresh_from_db()
    assert current.status == "running"
    assert worker.finish_job(job_id, claim_token=second) is True


def test_auth_email_delivery_uses_derived_token_without_storing_plaintext(monkeypatch):
    from taskiller.auth.security import derive_auth_email_token, hash_opaque_token
    from taskiller.django_api.runtime import taskiller_settings
    from taskiller.django_operations import email_delivery

    user = row(domain.TaskillerUser, email=f"{uuid4()}@example.test", is_active=True)
    token_id = uuid4()
    plain = derive_auth_email_token(token_id, "email_verification", taskiller_settings())
    row(
        domain.EmailVerificationToken,
        id=token_id,
        user_id=user.id,
        token_hash=hash_opaque_token(plain, taskiller_settings()),
        expires_at=utc_now() + timedelta(hours=1),
    )
    pending = job(
        "auth_email",
        payload_json={
            "tokenId": str(token_id),
            "userId": str(user.id),
            "kind": "email_verification",
        },
    )
    sent = []

    class Sender:
        async def send_email_verification(self, recipient, token):
            sent.append((recipient, token))

    monkeypatch.setattr(email_delivery, "auth_email_sender", Sender)
    worker._process_locked_job(pending)
    assert sent == [(user.email, plain)]
    pending.refresh_from_db()
    assert plain not in str(pending.payload_json)
    assert set(pending.payload_json) == {"tokenId", "userId", "kind"}


def test_terminal_retention_failure_is_rescheduled():
    failed = job(
        status="running",
        attempts=2,
        locked_by="lost",
        lease_expires_at=utc_now() - timedelta(seconds=1),
    )
    worker.recover_expired_leases()
    worker.ensure_retention_job()
    worker.ensure_retention_job()
    failed.refresh_from_db()
    assert failed.status == "dead"
    assert domain.OutboxJob.objects.filter(job_type="retention", status="queued").count() == 1


def test_process_export_snapshot_and_acknowledgement_are_atomic(monkeypatch):
    """Use an independent connection because process_job requires a fresh transaction."""
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connection, connections

    def scenario():
        current = job("data_export")
        marker = job("test_marker", payload_json={"value": "before"})
        try:

            def effects(locked_job):
                assert domain.OutboxJob.objects.get(id=marker.id).payload_json == {
                    "value": "before"
                }

                def concurrent_write():
                    try:
                        domain.OutboxJob.objects.filter(id=marker.id).update(
                            payload_json={"value": "after"}
                        )
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(concurrent_write).result(timeout=10)
                assert domain.OutboxJob.objects.get(id=marker.id).payload_json == {
                    "value": "before"
                }
                domain.OutboxJob.objects.filter(id=locked_job.id).update(
                    payload_json={"effect": True}
                )

            monkeypatch.setattr(worker, "_process_locked_job", effects)
            assert worker.process_job(current.id)
            current.refresh_from_db()
            assert current.status == "succeeded"
            assert current.payload_json == {"effect": True}

            domain.OutboxJob.objects.filter(id=current.id).update(status="queued", payload_json={})
            finish = worker._finish_locked_job

            def crash_before_ack(locked_job):
                finish(locked_job)
                raise RuntimeError("crash before commit")

            monkeypatch.setattr(
                worker,
                "_process_locked_job",
                lambda locked_job: domain.OutboxJob.objects.filter(id=locked_job.id).update(
                    payload_json={"effect": True}
                ),
            )
            monkeypatch.setattr(worker, "_finish_locked_job", crash_before_ack)
            with pytest.raises(RuntimeError, match="crash before commit"):
                worker.process_job(current.id)
            current.refresh_from_db()
            assert current.status == "queued"
            assert current.payload_json == {}
        finally:
            domain.OutboxJob.objects.filter(id__in=[current.id, marker.id]).delete()
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(scenario).result(timeout=20)
