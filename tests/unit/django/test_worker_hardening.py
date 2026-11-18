# ruff: noqa: E402
from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.db import OperationalError

from taskiller.django_operations import worker_service as worker
from taskiller.django_operations.management.commands import taskiller_worker as command


def test_account_deletion_removes_dependents_before_parents(monkeypatch):
    operations = []
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(worker.connection, "cursor", lambda: cursor)

    class Query:
        def __init__(self, name):
            self.name = name

        def filter(self, **kwargs):
            return self

        def select_for_update(self):
            return self

        def order_by(self, *fields):
            assert fields == ("id",)
            return self

        def __iter__(self):
            operations.append((self.name, "lock"))
            return iter(())

        def values(self, *args):
            return []

        def update(self, **kwargs):
            operations.append((self.name, "update"))

        def delete(self):
            operations.append((self.name, "delete"))

    names = (
        "TaskillerUser",
        "AuthSession",
        "RefreshToken",
        "EmailVerificationToken",
        "PasswordResetToken",
        "UserPreferences",
        "IdempotencyRecord",
        "DataExportRequest",
        "SessionEvent",
        "SessionReview",
        "ExecutionSession",
        "FocusPlanSegment",
        "FocusPlan",
        "FocusPlanRecommendation",
        "WorkItem",
        "WorkType",
    )
    for name in names:
        monkeypatch.setattr(getattr(worker, name), "objects", Query(name))
    deletion = SimpleNamespace(user_id=uuid4(), started_at=None, save=lambda **kw: None)
    worker._hard_delete_account(deletion)
    deleted = [name for name, action in operations if action == "delete"]
    assert deleted.index("SessionEvent") < deleted.index("ExecutionSession")
    assert deleted.index("SessionReview") < deleted.index("ExecutionSession")
    assert deleted.index("ExecutionSession") < deleted.index("FocusPlan")
    assert deleted.index("FocusPlanSegment") < deleted.index("FocusPlan")
    assert deleted.index("FocusPlan") < deleted.index("FocusPlanRecommendation")
    assert deleted.index("RefreshToken") < deleted.index("AuthSession")
    assert deleted.index("WorkItem") < deleted.index("WorkType")
    assert deleted[-1] == "TaskillerUser"
    assert ("RefreshToken", "update") in operations
    assert operations.index(("AuthSession", "lock")) < operations.index(("RefreshToken", "update"))
    assert deletion.status == "completed"


def test_parent_exits_when_worker_dies_and_stops_api(monkeypatch):
    import scripts.run_django_production as production

    worker_child = Mock()
    worker_child.poll.return_value = 7
    api = Mock()
    api.poll.return_value = None
    monkeypatch.setattr(
        production.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        production, "get_settings", lambda: SimpleNamespace(embedded_worker_enabled=True)
    )
    children = iter([worker_child, api])
    monkeypatch.setattr(production, "_spawn", lambda args: next(children))
    monkeypatch.setattr(production.signal, "signal", lambda *args: None)
    import pytest

    with pytest.raises(SystemExit) as exc:
        production.main()
    assert exc.value.code == 7
    api.terminate.assert_called_once()


def test_claim_generates_distinct_fence_per_attempt(monkeypatch):
    job = SimpleNamespace(id=uuid4(), attempts=0, save=lambda: None)
    query = Mock()
    query.filter.return_value.order_by.return_value.first.return_value = job
    monkeypatch.setattr(worker.OutboxJob.objects, "select_for_update", lambda **kw: query)
    monkeypatch.setattr(worker.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        worker, "taskiller_settings", lambda: SimpleNamespace(outbox_lease_seconds=60)
    )
    worker.claim_job("same-host")
    first = job.locked_by
    worker.claim_job("same-host")
    assert job.locked_by != first


def test_stale_acknowledgement_cannot_complete_job(monkeypatch):
    job = SimpleNamespace(status="running", locked_by="new", lease_expires_at=None)
    query = Mock()
    query.get.return_value = job
    monkeypatch.setattr(worker.OutboxJob.objects, "select_for_update", lambda **kw: query)
    monkeypatch.setattr(worker.transaction, "atomic", lambda: nullcontext())
    assert worker.finish_job(uuid4(), claim_token="old") is False
    assert job.status == "running"


def test_worker_recovers_after_startup_database_failure(monkeypatch):
    attempts = []

    def recover():
        attempts.append(1)
        if len(attempts) == 1:
            raise OperationalError("offline")

    monkeypatch.setattr(command, "recover_expired_leases", recover)
    monkeypatch.setattr(command, "ensure_retention_job", lambda: None)
    monkeypatch.setattr(command, "claim_job", lambda *args, **kw: None)
    monkeypatch.setattr(command.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(command, "close_old_connections", lambda: None, raising=False)
    monkeypatch.setattr(
        command, "connections", SimpleNamespace(close_all=lambda: None), raising=False
    )
    monkeypatch.setattr(
        command, "taskiller_settings", lambda: SimpleNamespace(outbox_poll_seconds=0)
    )
    command.Command().handle(once=True)
    assert len(attempts) == 2


def test_idle_worker_periodically_recovers_and_restores_retention(monkeypatch):
    import pytest

    maintained = []
    clock = iter([0, 0, 16, 16, 32, 32])
    claims = []

    class StopLoop(Exception):
        pass

    def claim(*args, **kwargs):
        claims.append(1)
        if len(claims) == 3:
            raise StopLoop
        return None

    monkeypatch.setattr(command.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(command.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(command, "close_old_connections", lambda: None)
    monkeypatch.setattr(command, "recover_expired_leases", lambda: maintained.append("recover"))
    monkeypatch.setattr(command, "ensure_retention_job", lambda: maintained.append("schedule"))
    monkeypatch.setattr(command, "claim_job", claim)
    monkeypatch.setattr(
        command, "taskiller_settings", lambda: SimpleNamespace(outbox_poll_seconds=0)
    )
    with pytest.raises(StopLoop):
        command.Command().handle(once=False)
    assert maintained == ["recover", "schedule"] * 3


def test_api_spawn_failure_terminates_already_started_worker(monkeypatch):
    import pytest
    import scripts.run_django_production as production

    child = Mock()
    child.poll.return_value = None
    calls = []

    def spawn(args):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("cannot start api")
        return child

    monkeypatch.setattr(
        production.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        production, "get_settings", lambda: SimpleNamespace(embedded_worker_enabled=True)
    )
    monkeypatch.setattr(production, "_spawn", spawn)
    monkeypatch.setattr(production.signal, "signal", lambda *args: None)
    with pytest.raises(OSError):
        production.main()
    child.terminate.assert_called_once()
