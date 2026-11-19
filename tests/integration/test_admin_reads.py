from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from taskiller.django_api.admin_api import queries as q
from taskiller.django_api.admin_api import read_views as v
from taskiller.django_api.admin_api.authentication import new_session
from taskiller.django_api.admin_api.permissions import ensure_roles
from taskiller.django_domain import models as m

pytestmark = pytest.mark.integration


@pytest.fixture
def window():
    now = timezone.now()
    return {"start": now - timedelta(days=2), "end": now + timedelta(seconds=1), "limit": 1}


def product_user(created_at=None):
    now = created_at or timezone.now()
    return m.TaskillerUser.objects.create(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        password_hash="PRIVATE_HASH",
        display_name="Sample",
        email_verified_at=None,
        password_changed_at=now,
        is_active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )


def job(kind="auth_email", status="dead", created_at=None):
    now = created_at or timezone.now()
    return m.OutboxJob.objects.create(
        id=uuid4(),
        job_type=kind,
        payload_json={"secret": "PRIVATE_PAYLOAD"},
        status=status,
        available_at=now,
        attempts=2,
        max_attempts=3,
        last_error="PRIVATE_PROVIDER_ERROR",
        created_at=now,
        updated_at=now,
    )


def staff(role):
    ensure_roles()
    user = get_user_model().objects.create_user(
        username=f"read-{uuid4()}",
        password="Password-for-fixture",
        is_staff=True,
    )
    user.groups.add(Group.objects.get(name=f"taskiller-console:{role}"))
    enrollment = m.StaffEnrollment.objects.create(user=user, mfa_secret_encrypted="encrypted")
    session, token = new_session(enrollment)
    return user, enrollment, session, token


def test_keyset_ties_are_stable_and_cursors_are_scoped(window):
    stamp = timezone.now()
    rows = [product_user(stamp) for _ in range(3)]
    expected = sorted((str(row.id) for row in rows), reverse=True)
    values = {**window, "start": stamp - timedelta(seconds=1), "end": stamp + timedelta(seconds=1)}
    first = q.users(values, "staff-a:users")
    assert str(first["items"][0]["id"]) == expected[0]
    second = q.users({**values, "cursor": first["nextCursor"]}, "staff-a:users")
    assert str(second["items"][0]["id"]) == expected[1]
    with pytest.raises(ValidationError):
        q.users({**values, "cursor": first["nextCursor"]}, "staff-b:users")
    with pytest.raises(ValidationError):
        q.users({**values, "cursor": first["nextCursor"], "verified": True}, "staff-a:users")


def test_job_scope_applies_before_pagination_and_omits_secrets(window):
    safe = job()
    job("data_export")
    job("account_delete")
    result = q.jobs(window, "staff:jobs")
    assert [item["id"] for item in result["items"]] == [safe.id]
    assert result["nextCursor"] is None
    assert "PRIVATE" not in str(result)
    filtered = q.jobs({**window, "type": "account_delete"}, "staff:jobs")
    assert filtered == {"items": [], "nextCursor": None}


def test_administrator_audit_excludes_owner_staff_and_private_rows(window):
    _, owner, _, _ = staff("Owner")
    _, admin, _, _ = staff("Administrator")
    target = str(uuid4())
    allowed = m.AdminAuditRecord.objects.create(
        actor_id=str(admin.id),
        action="users.suspend",
        target_type="users",
        target_id=target,
    )
    for actor, action, kind in (
        (owner.id, "users.suspend", "users"),
        (admin.id, "staff.roles", "staff"),
        (admin.id, "work.read", "project"),
        (admin.id, "privacy.read", "export"),
    ):
        m.AdminAuditRecord.objects.create(
            actor_id=str(actor),
            action=action,
            target_type=kind,
            target_id=target,
        )
    # A staff-management actor is conservatively hidden even after later role changes.
    assert not q.scoped_audit(False).filter(pk=allowed.id).exists()
    other = m.AdminAuditRecord.objects.create(
        actor_id=str(uuid4()),
        action="users.recovery-email",
        target_type="users",
        target_id=target,
    )
    assert list(q.scoped_audit(False).values_list("id", flat=True)) == [other.id]
    assert q.scoped_audit(True).filter(pk=allowed.id).exists()


def test_pending_deletion_is_distinct_from_suspension(window):
    user = product_user()
    m.TaskillerUser.objects.filter(pk=user.id).update(suspended_at=timezone.now(), is_active=False)
    assert q.user_projection(q.users_queryset().get(pk=user.id))["lifecycle"] == "suspended"
    now = timezone.now()
    m.AccountDeletionRequest.objects.create(
        id=uuid4(),
        user_id=user.id,
        status="scheduled",
        requested_at=now,
        execute_after=now + timedelta(days=7),
    )
    assert q.user_projection(q.users_queryset().get(pk=user.id))["lifecycle"] == "pending_deletion"
    assert q.users({**window, "lifecycle": "suspended"}, "users")["items"] == []


def test_overview_uses_completion_time_and_recorded_event_time(window):
    user = product_user()
    now = timezone.now()
    work = m.WorkItem.objects.create(
        id=uuid4(),
        owner=user,
        kind="chore",
        name="PRIVATE",
        status="ready",
        position=0,
        created_at=now,
        updated_at=now,
        version=1,
    )
    plan = m.FocusPlan.objects.create(
        id=uuid4(),
        owner=user,
        work_item=work,
        source="manual",
        name="PRIVATE",
        is_template=False,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session = m.ExecutionSession.objects.create(
        id=uuid4(),
        owner=user,
        work_item=work,
        focus_plan=plan,
        state="completed",
        current_segment_index=0,
        session_started_at=now - timedelta(days=3),
        ended_at=now,
        plan_snapshot_json={},
        work_context_snapshot_json={},
        created_at=now - timedelta(days=3),
        updated_at=now,
        version=1,
    )
    for _ in range(2):
        m.SessionEvent.objects.create(
            id=uuid4(),
            session=session,
            owner=user,
            type="session_completed",
            occurred_at=now,
            idempotency_key=str(uuid4()),
            request_hash="a" * 64,
            payload_json={"private": "SECRET"},
            result_session_snapshot_json={},
            created_at=now,
        )
    result = q.overview(window)
    assert result["completedExecutionSessions"] >= 1
    assert result["accountsWithExecutionActivity"] >= 1
    assert result["queuedJobs"] is None
    assert result["latestWorkerSignalAt"] is None
    assert "SECRET" not in str(result)


def test_activity_cursor_omits_payloads_and_support_security_rows(window):
    user = product_user()
    for number in range(2):
        m.SecurityEvent.objects.create(
            id=uuid4(),
            user_id=user.id,
            event_type="login_success",
            metadata_json={"secret": number},
            created_at=timezone.now(),
        )
    support = q.activity(window, "support", user.id, security=False)
    assert support["items"] == []
    admin = q.activity(window, "admin", user.id, security=True)
    assert len(admin["items"]) == 1
    second = q.activity({**window, "cursor": admin["nextCursor"]}, "admin", user.id, security=True)
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] != admin["items"][0]["id"]
    assert "secret" not in str(admin)


@override_settings(
    ADMIN_CONSOLE_ENABLED=True,
    ADMIN_CONSOLE_WRITES_ENABLED=False,
    ADMIN_CONSOLE_ORIGINS=["https://console.example.com"],
)
def test_staff_read_boundary_and_search_csrf():
    _, _, session, token = staff("Support")
    factory = APIRequestFactory(HTTP_COOKIE=f"taskiller_staff={token}")
    account = product_user()
    response = v.UserDetailView.as_view()(factory.get("/users"), user_id=account.id)
    assert response.status_code == 200
    assert response["ETag"] == f'"user:{account.id}:v1"'
    assert "no-store" in response["Cache-Control"]
    denied = v.UserSearchView.as_view()(
        factory.post(
            "/users/search",
            {"query": account.email},
            format="json",
            HTTP_ORIGIN="https://console.example.com",
        )
    )
    assert denied.status_code == 403
    forbidden = v.UserWorkView.as_view()(
        factory.get("/work", {"kind": "chore"}), user_id=account.id
    )
    assert forbidden.status_code == 403
    m.StaffSession.objects.filter(pk=session.id).update(revoked_at=timezone.now())
    revoked = v.UserDetailView.as_view()(factory.get("/users"), user_id=account.id)
    assert revoked.status_code == 401
    assert UUID(str(account.id)) == account.id


@override_settings(
    ADMIN_CONSOLE_ENABLED=True,
    ADMIN_CONSOLE_WRITES_ENABLED=False,
    ADMIN_CONSOLE_ORIGINS=["https://console.example.com"],
    CSRF_TRUSTED_ORIGINS=["https://console.example.com"],
)
def test_search_is_a_csrf_protected_read_with_writes_disabled():
    from django.middleware.csrf import _get_new_csrf_string

    _, _, _, token = staff("Support")
    csrf = _get_new_csrf_string()
    factory = APIRequestFactory(HTTP_COOKIE=f"taskiller_staff={token}; taskiller_staff_csrf={csrf}")
    user = product_user()
    response = v.UserSearchView.as_view()(
        factory.post(
            "/users/search",
            {"query": user.email},
            format="json",
            HTTP_ORIGIN="https://console.example.com",
            HTTP_X_CSRFTOKEN=csrf,
        )
    )
    assert response.status_code == 200
    assert response.data["items"][0]["id"] == str(user.id)
    assert "PRIVATE_HASH" not in str(response.data)


def test_privacy_jobs_retry_eligibility_is_scoped_and_redacted(window):
    user = product_user()
    now = timezone.now()
    export = m.DataExportRequest.objects.create(
        id=uuid4(),
        user=user,
        status="failed",
        created_at=now,
    )
    export_job = job("data_export")
    m.OutboxJob.objects.filter(pk=export_job.id).update(
        payload_json={
            "exportRequestId": str(export.id),
            "userId": str(user.id),
            "secret": "PRIVATE",
        }
    )
    values = {**window, "type": "data_export"}
    result = q.jobs(values, "owner", include_privacy=True, retry=True)
    assert result["items"][0]["eligibleActions"] == ["retry"]
    assert "PRIVATE" not in str(result)
    m.DataExportRequest.objects.filter(pk=export.id).update(status="completed")
    assert (
        q.jobs(values, "owner", include_privacy=True, retry=True)["items"][0]["eligibleActions"]
        == []
    )
    assert q.jobs(values, "admin")["items"] == []


def test_overview_uses_same_privacy_queue_scope_as_jobs(window):
    before_admin = q.overview(window, operations=True)
    before_owner = q.overview(window, operations=True, include_privacy=True)
    job("data_export", status="queued")
    job("account_delete", status="dead")
    after_admin = q.overview(window, operations=True)
    after_owner = q.overview(window, operations=True, include_privacy=True)
    assert after_admin["queuedJobs"] == before_admin["queuedJobs"]
    assert after_admin["failedJobs"] == before_admin["failedJobs"]
    assert after_owner["queuedJobs"] == before_owner["queuedJobs"] + 1
    assert after_owner["failedJobs"] == before_owner["failedJobs"] + 1
    owner_jobs = q.jobs({**window, "limit": 100}, "owner", include_privacy=True)
    assert {item["type"] for item in owner_jobs["items"]} >= {"data_export", "account_delete"}


@override_settings(ADMIN_CONSOLE_ENABLED=True)
def test_private_focus_detail_orders_segments_and_records_audit():
    _, enrollment, _, token = staff("Owner")
    owner = product_user()
    now = timezone.now()
    plan = m.FocusPlan.objects.create(
        id=uuid4(),
        owner=owner,
        source="manual",
        name="Private Focus Plan",
        is_template=False,
        created_at=now,
        updated_at=now,
        version=1,
    )
    for index in (7, 2):
        m.FocusPlanSegment.objects.create(
            id=uuid4(),
            focus_plan=plan,
            segment_index=index,
            kind="work",
            duration_mode="fixed",
            target_seconds=1200,
            optional=False,
            label=f"Segment {index}",
            instructions="NOT_IN_ADMIN_PROJECTION",
        )
    factory = APIRequestFactory(HTTP_COOKIE=f"taskiller_staff={token}")
    response = v.WorkDetailView.as_view()(
        factory.get("/work", {"kind": "focus_plan"}),
        work_id=plan.id,
    )
    assert response.status_code == 200
    assert [segment["segmentIndex"] for segment in response.data["segments"]] == [2, 7]
    assert response.data["source"] == "manual"
    assert response["ETag"] == f'"focus-plan:{plan.id}:v1"'
    assert "NOT_IN_ADMIN_PROJECTION" not in str(response.data)
    assert m.AdminAuditRecord.objects.filter(
        actor_id=str(enrollment.id),
        action="work.read",
        target_type="focus_plan",
        target_id=str(plan.id),
        outcome="success",
    ).exists()
    listing = q.page(
        q.bounded(
            q.work_queryset("focus_plan", owner.id),
            {"start": now - timedelta(seconds=1), "end": now + timedelta(seconds=1)},
        ),
        {"start": now - timedelta(seconds=1), "end": now + timedelta(seconds=1), "limit": 25},
        "work-list",
        lambda row: q.work_projection(row, "focus_plan"),
    )
    assert "segments" not in listing["items"][0]
    assert "source" not in listing["items"][0]
