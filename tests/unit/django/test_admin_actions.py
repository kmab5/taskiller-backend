# ruff: noqa: E402
from __future__ import annotations

import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest

from taskiller.django_api.admin_api import actions
from taskiller.django_api.admin_api.action_serializers import (
    AccountCommandSerializer,
    BulkCommandSerializer,
    InvitationSerializer,
    WorkCorrectionSerializer,
)
from taskiller.django_api.errors import TaskillerAPIError

REASON = {"reasonCode": "support_request", "comment": "Approved correction"}


def test_command_requires_reason_and_rejects_unknown_fields():
    assert not AccountCommandSerializer(data={}).is_valid()
    assert not AccountCommandSerializer(data={"reason": REASON, "password": "secret"}).is_valid()
    assert not AccountCommandSerializer(data={"reason": {"reasonCode": " "}}).is_valid()
    assert AccountCommandSerializer(data={"reason": REASON}).is_valid()


def test_invitation_accepts_only_predefined_unique_roles():
    payload = {"reason": REASON, "username": "operator", "email": "op@example.test"}
    for roles in (["Superuser"], ["Owner", "Owner"], []):
        assert not InvitationSerializer(data={**payload, "roles": roles}).is_valid()
    assert InvitationSerializer(data={**payload, "roles": ["Support"]}).is_valid()


def test_work_correction_requires_mapped_operation():
    assert not WorkCorrectionSerializer(
        data={"reason": REASON, "operation": "raw-sql", "correction": {"sql": "anything"}}
    ).is_valid()


@pytest.mark.parametrize("count", [0, 51])
def test_bulk_is_bounded(count):
    payload = {
        "reason": REASON,
        "action": "suspend",
        "targets": [{"id": uuid4()} for _ in range(count)],
    }
    assert not BulkCommandSerializer(data=payload).is_valid()
    with pytest.raises(TaskillerAPIError):
        actions._validate_bulk(payload)


def test_bulk_rejects_duplicate_targets():
    target = uuid4()
    serializer = BulkCommandSerializer(
        data={
            "reason": REASON,
            "action": "revoke-sessions",
            "targets": [{"id": target}, {"id": target}],
        }
    )
    assert not serializer.is_valid()


def test_bulk_keeps_partial_results_and_stable_per_target_keys(monkeypatch):
    first, second = uuid4(), uuid4()
    call = Mock(
        side_effect=[
            {"status": "completed"},
            TaskillerAPIError(412, "precondition_failed", "Stale"),
        ]
    )
    monkeypatch.setattr(actions, "execute", call)
    data = {"reason": REASON, "action": "suspend", "targets": [{"id": first}, {"id": second}]}
    result = actions.bulk_execute(object(), data, key="bulk-intent-123")
    assert [row["outcome"] for row in result["results"]] == ["success", "failed"]
    assert result["results"][1]["code"] == "precondition_failed"
    assert call.call_args_list[0].kwargs["key"] != call.call_args_list[1].kwargs["key"]
    assert call.call_args_list[0].kwargs["key"] == actions._digest(f"bulk-intent-123:{first}")


def test_unexpected_bulk_failure_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr(actions, "execute", Mock(side_effect=RuntimeError("credential material")))
    result = actions.bulk_execute(
        object(),
        {"reason": REASON, "action": "revoke-sessions", "targets": [{"id": uuid4()}]},
        key="bulk-intent-123",
    )
    assert result["results"][0]["code"] == "internal_error"
    assert "credential" not in str(result)


def test_replay_hash_binds_payload_and_etag(monkeypatch):
    receipt = SimpleNamespace(request_hash="different")
    query = Mock()
    query.filter.return_value.first.return_value = receipt
    monkeypatch.setattr(actions.AdminCommandReceipt, "objects", query)
    with pytest.raises(TaskillerAPIError) as exc:
        actions._receipt(
            object(),
            SimpleNamespace(id=uuid4()),
            "users.suspend",
            uuid4(),
            {"reason": REASON},
            "intent-key-123",
            '"user:old:v1"',
        )
    assert exc.value.code == "idempotency_conflict"


def test_replay_rechecks_current_authority(monkeypatch):
    actor = SimpleNamespace(id=uuid4())
    denied = TaskillerAPIError(403, "admin_permission_denied", "Denied")
    policy = Mock(side_effect=[None, None, denied])
    monkeypatch.setattr(actions, "_policy", policy)
    monkeypatch.setattr(actions, "_lock_actor", lambda request: actor)
    monkeypatch.setattr(actions.transaction, "atomic", nullcontext)
    monkeypatch.setattr(actions.settings, "ADMIN_CONSOLE_WRITES_ENABLED", True)
    monkeypatch.setattr(actions, "record", Mock())
    query = Mock()
    query.filter.return_value.first.return_value = SimpleNamespace(
        request_hash=actions._digest(
            json.dumps(
                {"payload": {"reason": REASON}, "ifMatch": None},
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
        response_json={"status": "completed"},
    )
    monkeypatch.setattr(actions.AdminCommandReceipt, "objects", query)
    with pytest.raises(TaskillerAPIError) as exc:
        actions.execute(
            object(), "users.revoke-sessions", uuid4(), {"reason": REASON}, key="intent-key-123"
        )
    assert exc.value.status_code == 403
    assert policy.call_count == 3


def test_success_receipt_omits_invitation_token(monkeypatch):
    monkeypatch.setattr(actions, "_policy", Mock())
    monkeypatch.setattr(actions, "_lock_actor", lambda request: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(actions, "_receipt", lambda *args: (None, "hash", "digest"))
    monkeypatch.setattr(actions.transaction, "atomic", nullcontext)
    monkeypatch.setattr(actions, "owner_lock", nullcontext)
    monkeypatch.setattr(actions.settings, "ADMIN_CONSOLE_WRITES_ENABLED", True)
    monkeypatch.setattr(
        actions,
        "_dispatch",
        lambda *args: (
            {"status": "invited", "invitationToken": "one-time-secret"},
            {"roles": ["Support"]},
        ),
    )
    audit = Mock()
    monkeypatch.setattr(actions, "record", audit)
    query = Mock()
    monkeypatch.setattr(actions.AdminCommandReceipt, "objects", query)
    result = actions.execute(
        object(), "staff.invite", "invitations", {"reason": REASON}, key="intent-key-123"
    )
    assert result["invitationToken"] == "one-time-secret"
    assert "invitationToken" not in query.create.call_args.kwargs["response_json"]
    assert "one-time-secret" not in str(audit.call_args)


def test_retry_whitelist_excludes_irreversible_and_delivery_jobs():
    assert actions.RETRYABLE_JOB_TYPES == {"data_export"}


@pytest.mark.parametrize(
    "job_type,status",
    [
        ("auth_email", "dead"),
        ("account_delete", "dead"),
        ("data_export", "succeeded"),
        ("data_export", "running"),
        ("retention", "dead"),
    ],
)
def test_unsafe_jobs_are_not_retried(monkeypatch, job_type, status):
    monkeypatch.setattr(actions, "_job_policy", Mock())
    monkeypatch.setattr(
        actions, "_get", lambda *args, **kwargs: SimpleNamespace(job_type=job_type, status=status)
    )
    with pytest.raises(TaskillerAPIError) as exc:
        actions._retry(object(), uuid4())
    assert exc.value.code == "job_not_retryable"


def test_command_views_use_write_rollout_gate_and_staff_authentication():
    from taskiller.django_api.admin_api.action_views import (
        BulkExecuteView,
        BulkPreviewView,
        CommandView,
        StaffRolesView,
    )
    from taskiller.django_api.admin_api.authentication import StaffAuthentication

    for view in (CommandView, StaffRolesView, BulkPreviewView, BulkExecuteView):
        assert view.writes
        assert view.authentication_classes == (StaffAuthentication,)
    assert StaffRolesView.http_method_names == ["patch", "options"]
