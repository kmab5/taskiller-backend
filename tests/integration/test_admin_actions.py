# ruff: noqa: E402
from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
import django

django.setup()

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from taskiller.django_api.admin_api import actions
from taskiller.django_api.admin_api.authentication import auth_hash, digest
from taskiller.django_api.admin_api.permissions import ensure_roles
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.privacy_service import request_data_export
from taskiller.django_api.work_service import DjangoWorkService
from taskiller.django_domain.models import (
    AccountDeletionRequest,
    AdminAuditRecord,
    AdminCommandReceipt,
    AuthSession,
    DataExportRequest,
    OutboxJob,
    StaffChallenge,
    StaffEnrollment,
    StaffSession,
    TaskillerUser,
    WorkItem,
)
from taskiller.users.etag import make_etag
from taskiller.work.schemas import CreateWorkItemRequest

pytestmark = pytest.mark.integration
REASON = {"reasonCode": "support_request", "comment": "Confirmed by account owner"}


@pytest.fixture(autouse=True)
def admin_settings(monkeypatch):
    monkeypatch.setattr(actions.settings, "ADMIN_CONSOLE_ENABLED", True)
    monkeypatch.setattr(actions.settings, "ADMIN_CONSOLE_WRITES_ENABLED", True)
    ensure_roles()


def staff(role="Owner"):
    user = get_user_model().objects.create_user(
        username="staff-" + uuid4().hex,
        password="unused-test-password",
        is_staff=True,
        email=f"{uuid4().hex}@example.test",
    )
    user.groups.add(Group.objects.get(name="taskiller-console:" + role))
    enrollment = StaffEnrollment.objects.create(user=user, mfa_secret_encrypted="test-encrypted")
    now = timezone.now()
    session = StaffSession.objects.create(
        enrollment=enrollment,
        token_digest=uuid4().hex,
        auth_hash=auth_hash(enrollment),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=1),
        mfa_verified_at=now,
    )
    request = SimpleNamespace(
        user=user, auth=session, _auth=session, taskiller_request_id=uuid4().hex
    )
    return request, enrollment


def product_user():
    now = timezone.now()
    return TaskillerUser.objects.create(
        id=uuid4(),
        email=f"{uuid4().hex}@example.test",
        password_hash="unused",
        password_changed_at=now,
        is_active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )


def product_session(user):
    now = timezone.now()
    return AuthSession.objects.create(
        id=uuid4(),
        user=user,
        device_name="test",
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=1),
    )


def command(request, action, target, *, data=None, key=None, etag=None):
    return actions.execute(
        request,
        action,
        target,
        data or {"reason": REASON},
        key=key or str(uuid4()),
        if_match=etag,
    )


def test_suspend_reactivate_does_not_revive_product_sessions():
    request, _ = staff()
    user = product_user()
    session = product_session(user)
    result = command(request, "users.suspend", user.id, etag=make_etag("user", user.id, 1))
    user.refresh_from_db()
    session.refresh_from_db()
    assert not user.is_active and user.suspended_at is not None
    assert session.revoked_at is not None
    assert AdminAuditRecord.objects.get(action="users.suspend", target_id=str(user.id)).reason_code
    command(request, "users.reactivate", user.id, etag=result["etag"])
    user.refresh_from_db()
    session.refresh_from_db()
    assert user.is_active and user.suspended_at is None
    assert session.revoked_at is not None


def test_stale_etag_leaves_only_failure_audit():
    request, _ = staff()
    user = product_user()
    with pytest.raises(TaskillerAPIError) as exc:
        command(request, "users.suspend", user.id, etag=make_etag("user", user.id, 99))
    assert exc.value.status_code == 412
    user.refresh_from_db()
    assert user.is_active and user.version == 1
    assert not AdminCommandReceipt.objects.filter(target_id=str(user.id)).exists()
    assert list(
        AdminAuditRecord.objects.filter(target_id=str(user.id)).values_list("outcome", flat=True)
    ) == ["failed"]


def test_success_audit_failure_rolls_back_account_and_receipt(monkeypatch):
    request, _ = staff()
    user = product_user()
    original_record = actions.record

    def failing_success_audit(*args, **kwargs):
        if kwargs.get("outcome", "success") == "success":
            raise RuntimeError("Audit storage unavailable")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(actions, "record", failing_success_audit)
    with pytest.raises(RuntimeError):
        command(request, "users.suspend", user.id, etag=make_etag("user", user.id, 1))
    user.refresh_from_db()
    assert user.is_active and user.suspended_at is None
    assert not AdminCommandReceipt.objects.filter(target_id=str(user.id)).exists()
    assert not AdminAuditRecord.objects.filter(target_id=str(user.id), outcome="success").exists()


def test_replay_is_bound_to_payload_and_rechecks_permission():
    request, _ = staff("Administrator")
    user = product_user()
    key = str(uuid4())
    command(request, "users.revoke-sessions", user.id, key=key)
    assert command(request, "users.revoke-sessions", user.id, key=key)["replayed"]
    with pytest.raises(TaskillerAPIError) as exc:
        command(
            request,
            "users.revoke-sessions",
            user.id,
            key=key,
            data={"reason": {"reasonCode": "different_reason"}},
        )
    assert exc.value.code == "idempotency_conflict"
    request.user.groups.clear()
    with pytest.raises(TaskillerAPIError) as exc:
        command(request, "users.revoke-sessions", user.id, key=key)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("change", ["password", "idle", "role"])
def test_locked_actor_rejects_inflight_authentication_changes(change):
    request, _ = staff()
    if change == "password":
        request.user.set_password("changed-password-test")
        request.user.save(update_fields=["password"])
    elif change == "idle":
        StaffSession.objects.filter(id=request.auth.id).update(
            last_seen_at=timezone.now() - timedelta(minutes=31)
        )
    else:
        request.user.groups.add(Group.objects.get(name="taskiller-console:Support"))
        # The union of capabilities is unchanged for Owner. Change version as a reset would.
        StaffEnrollment.objects.filter(id=request.auth.enrollment_id).update(version=2)
    with pytest.raises(TaskillerAPIError) as exc:
        command(request, "users.revoke-sessions", product_user().id)
    assert exc.value.status_code == 401


def test_suspension_rejects_deletion_pending_account():
    request, _ = staff()
    user = product_user()
    now = timezone.now()
    AccountDeletionRequest.objects.create(
        id=uuid4(),
        user_id=user.id,
        status="scheduled",
        requested_at=now,
        execute_after=now + timedelta(days=7),
    )
    with pytest.raises(TaskillerAPIError) as exc:
        command(request, "users.suspend", user.id, etag=make_etag("user", user.id, 1))
    assert exc.value.code == "account_deletion_pending"


def test_staff_invitation_is_one_hour_hashed_secret_returned_once():
    request, _ = staff()
    key = str(uuid4())
    data = {
        "reason": REASON,
        "username": "invited-" + uuid4().hex,
        "email": f"{uuid4().hex}@example.test",
        "roles": ["Support"],
    }
    result = command(request, "staff.invite", "invitations", data=data, key=key)
    invitation = StaffChallenge.objects.get(id=result["invitationId"])
    enrollment = invitation.enrollment
    assert invitation.purpose == "enrollment"
    assert invitation.secret_digest == digest(result["invitationToken"])
    assert timezone.now() < invitation.expires_at <= timezone.now() + timedelta(hours=1)
    assert invitation.consumed_at is None and enrollment.enabled
    assert invitation.payload_json == {"userId": str(enrollment.user_id), "roles": ["Support"]}
    assert not enrollment.user.has_usable_password()
    assert enrollment.user.groups.filter(name="taskiller-console:Support").exists()
    replay = command(request, "staff.invite", "invitations", data=data, key=key)
    assert "invitationToken" not in replay
    assert StaffChallenge.objects.filter(enrollment=enrollment).count() == 1
    assert result["invitationToken"] not in str(list(AdminCommandReceipt.objects.values()))
    assert result["invitationToken"] not in str(list(AdminAuditRecord.objects.values()))


def test_last_owner_and_self_grants_are_protected():
    request, enrollment = staff()
    with pytest.raises(TaskillerAPIError) as exc:
        command(
            request,
            "staff.revoke-access",
            enrollment.id,
            etag=make_etag("staff", enrollment.id, enrollment.version),
        )
    assert exc.value.status_code == 409
    with pytest.raises(TaskillerAPIError) as exc:
        command(
            request,
            "staff.roles",
            enrollment.id,
            data={"reason": REASON, "roles": ["Owner", "Support"]},
            etag=make_etag("staff", enrollment.id, enrollment.version),
        )
    assert exc.value.code == "self_grant_forbidden"


def test_staff_role_change_bumps_version_and_revokes_sessions():
    request, _ = staff()
    other, target = staff("Support")
    command(
        request,
        "staff.roles",
        target.id,
        data={"reason": REASON, "roles": ["Administrator"]},
        etag=make_etag("staff", target.id, target.version),
    )
    target.refresh_from_db()
    other.auth.refresh_from_db()
    assert target.version == 2 and other.auth.revoked_at is not None
    assert target.user.groups.filter(name="taskiller-console:Administrator").exists()
    assert not target.user.groups.filter(name="taskiller-console:Support").exists()


def test_dead_export_retry_replays_without_duplicate_jobs():
    request, _ = staff()
    user = product_user()
    export = request_data_export(user_id=user.id, idempotency_key=str(uuid4()))
    job = OutboxJob.objects.get(
        job_type="data_export", payload_json__exportRequestId=str(export.id)
    )
    DataExportRequest.objects.filter(id=export.id).update(status="failed")
    OutboxJob.objects.filter(id=job.id).update(status="dead", attempts=job.max_attempts)
    key = str(uuid4())
    command(request, "jobs.retry", job.id, key=key)
    assert command(request, "jobs.retry", job.id, key=key)["replayed"]
    job.refresh_from_db()
    export.refresh_from_db()
    assert job.status == "queued" and job.attempts == 0 and export.status == "queued"
    assert OutboxJob.objects.filter(payload_json__exportRequestId=str(export.id)).count() == 1


def test_privacy_commands_use_existing_services_and_redact_receipts():
    request, _ = staff()
    user = product_user()
    result = command(request, "privacy.export", user.id)
    assert DataExportRequest.objects.get(id=result["requestId"]).user_id == user.id
    deletion = command(request, "privacy.deletion", user.id, etag=make_etag("user", user.id, 1))
    assert AccountDeletionRequest.objects.get(id=deletion["requestId"]).user_id == user.id
    user.refresh_from_db()
    assert not user.is_active
    for receipt in AdminCommandReceipt.objects.filter(target_id=str(user.id)):
        assert "downloadUrl" not in receipt.response_json
        assert "archive_bytes" not in receipt.response_json


def test_work_correction_uses_domain_transition_and_redacts_content():
    request, _ = staff()
    user = product_user()
    item = DjangoWorkService(user.id).create_work_item(
        CreateWorkItemRequest(kind="chore", name="Private title", status="ready"), str(uuid4())
    )
    result = command(
        request,
        "work.correct",
        item["id"],
        data={"reason": REASON, "operation": "update-item", "correction": {"status": "completed"}},
        etag=make_etag("work-item", item["id"], 1),
    )
    row = WorkItem.objects.get(id=item["id"])
    assert row.status == "completed" and row.completed_at is not None
    assert "Private title" not in str(result)
    assert "Private title" not in str(list(AdminCommandReceipt.objects.values()))


def test_bulk_partial_results_are_independent_and_retryable():
    request, _ = staff()
    first, second = product_user(), product_user()
    data = {
        "reason": REASON,
        "action": "suspend",
        "targets": [
            {"id": first.id, "etag": make_etag("user", first.id, 1)},
            {"id": second.id, "etag": make_etag("user", second.id, 99)},
        ],
    }
    preview = actions.bulk_preview(request, data)
    assert preview["eligibleCount"] == 1
    key = str(uuid4())
    result = actions.bulk_execute(request, data, key=key)
    assert [row["outcome"] for row in result["results"]] == ["success", "failed"]
    replay = actions.bulk_execute(request, data, key=key)
    assert replay["results"][0]["result"]["replayed"]
    first.refresh_from_db()
    second.refresh_from_db()
    assert not first.is_active and second.is_active


def test_data_export_retry_requires_privacy_grant_even_on_replay():
    request, _ = staff()
    limited, _ = staff("Administrator")
    user = product_user()
    export = request_data_export(user_id=user.id, idempotency_key=str(uuid4()))
    job = OutboxJob.objects.get(
        job_type="data_export", payload_json__exportRequestId=str(export.id)
    )
    DataExportRequest.objects.filter(id=export.id).update(status="failed")
    OutboxJob.objects.filter(id=job.id).update(status="dead", attempts=job.max_attempts)
    with pytest.raises(TaskillerAPIError) as exc:
        command(limited, "jobs.retry", job.id)
    assert exc.value.status_code == 403
    job.refresh_from_db()
    assert job.status == "dead"
    key = str(uuid4())
    command(request, "jobs.retry", job.id, key=key)
    request.user.groups.clear()
    request.user.groups.add(Group.objects.get(name="taskiller-console:Administrator"))
    # Match the new role hash to exercise replay permission rather than hash revocation.
    request.auth.enrollment.user = request.user
    StaffSession.objects.filter(id=request.auth.id).update(
        auth_hash=auth_hash(request.auth.enrollment)
    )
    with pytest.raises(TaskillerAPIError) as exc:
        command(request, "jobs.retry", job.id, key=key)
    assert exc.value.status_code == 403


def test_pending_owner_invitation_does_not_replace_last_enrolled_owner():
    request, enrollment = staff()
    command(
        request,
        "staff.invite",
        "invitations",
        data={
            "reason": REASON,
            "username": "pending-" + uuid4().hex,
            "email": f"{uuid4().hex}@example.test",
            "roles": ["Owner"],
        },
    )
    with pytest.raises(TaskillerAPIError) as exc:
        command(
            request,
            "staff.revoke-access",
            enrollment.id,
            etag=make_etag("staff", enrollment.id, enrollment.version),
        )
    assert exc.value.status_code == 409


def test_suspension_leaves_running_execution_session_unchanged():
    from taskiller.django_api.execution_service import DjangoExecutionService
    from taskiller.django_api.focus_service import DjangoFocusService
    from taskiller.django_domain.models import ExecutionSession
    from taskiller.execution.schemas import StartExecutionSessionRequest
    from taskiller.focus.schemas import CreateFocusPlanRequest

    request, _ = staff()
    user = product_user()
    item = DjangoWorkService(user.id).create_work_item(
        CreateWorkItemRequest(kind="chore", name="Running work", status="ready"), str(uuid4())
    )
    plan = DjangoFocusService(user.id).create_focus_plan(
        CreateFocusPlanRequest.model_validate(
            {
                "workItemId": item["id"],
                "source": "manual",
                "name": "Running plan",
                "segments": [{"kind": "work", "durationMode": "fixed", "targetSeconds": 60}],
            }
        ),
        str(uuid4()),
    )
    execution = DjangoExecutionService(user.id).start_session(
        StartExecutionSessionRequest(work_item_id=item["id"], focus_plan_id=plan["id"]),
        str(uuid4()),
    )
    command(request, "users.suspend", user.id, etag=make_etag("user", user.id, 1))
    row = ExecutionSession.objects.get(id=execution["id"])
    assert row.state == "running" and row.ended_at is None


def test_bulk_staff_uses_single_command_owner_protection_and_partial_results():
    request, actor = staff()
    other, target = staff("Support")
    result = actions.bulk_execute(
        request,
        {
            "reason": REASON,
            "action": "staff.revoke-access",
            "targets": [
                {"id": target.id, "etag": make_etag("staff", target.id, target.version)},
                {"id": actor.id, "etag": make_etag("staff", actor.id, actor.version)},
            ],
        },
        key=str(uuid4()),
    )
    assert [row["outcome"] for row in result["results"]] == ["success", "failed"]
    target.refresh_from_db()
    actor.refresh_from_db()
    other.auth.refresh_from_db()
    assert not target.enabled and actor.enabled and other.auth.revoked_at is not None


def test_reissuing_invitation_consumes_previous_challenge():
    request, _ = staff()
    payload = {
        "reason": REASON,
        "username": "invited-" + uuid4().hex,
        "email": f"{uuid4().hex}@example.test",
        "roles": ["Support"],
    }
    first = command(request, "staff.invite", "invitations", data=payload)
    second = command(request, "staff.invite", "invitations", data=payload)
    previous = StaffChallenge.objects.get(id=first["invitationId"])
    current = StaffChallenge.objects.get(id=second["invitationId"])
    assert previous.consumed_at is not None and current.consumed_at is None
    assert previous.secret_digest != current.secret_digest
