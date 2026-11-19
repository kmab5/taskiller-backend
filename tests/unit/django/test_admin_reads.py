# ruff: noqa: E402
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

import pytest
from django.core import signing
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from taskiller.django_api.admin_api import queries as q
from taskiller.django_api.admin_api import read_serializers as s
from taskiller.django_api.admin_api import read_views as v


def test_filters_bound_every_query_and_reject_unknown_or_repeated_values():
    for data in (
        {"limit": 101},
        {"limit": 0},
        {"payload": "secret"},
        QueryDict("limit=1&limit=2"),
        {"query": "ab"},
    ):
        serializer = s.UserFiltersSerializer(data=data)
        assert not serializer.is_valid()
    now = datetime.now(UTC)
    for start, end in ((now - timedelta(days=91), now), (now, now), (now, now + timedelta(days=1))):
        serializer = s.ReadFiltersSerializer(data={"start": start, "end": end})
        assert not serializer.is_valid()
    serializer = s.ReadFiltersSerializer(data={})
    assert serializer.is_valid()
    assert serializer.validated_data["limit"] == 25
    assert serializer.validated_data["end"].utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value", ["bad", "x" * 2000, signing.dumps({"id": "bad"}, salt=q.CURSOR_SALT)]
)
def test_bad_cursor_is_a_validation_error(value):
    with pytest.raises(ValidationError):
        q.decode_cursor(value)


@pytest.mark.parametrize("search", [False, True])
def test_directory_has_no_implicit_registration_start(search):
    data = {"query": "old@example.com"} if search else {}
    serializer = s.UserFiltersSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    filters = serializer.validated_data
    assert "start" not in filters
    queryset = Mock()
    queryset.filter.return_value = queryset
    with patch.object(q, "users_queryset", return_value=queryset), patch.object(q, "page"):
        q.users(filters, "actor:users")
    assert queryset.filter.call_args_list[0].kwargs == {"created_at__lt": filters["end"]}


@pytest.mark.parametrize(
    "query, expected", [("", None), ("verified=true", True), ("verified=false", False)]
)
def test_directory_get_does_not_invent_a_verification_filter(query, expected):
    serializer = s.UserFiltersSerializer(data=QueryDict(query))
    assert serializer.is_valid(), serializer.errors
    if expected is None:
        assert "verified" not in serializer.validated_data
    else:
        assert serializer.validated_data["verified"] is expected


def test_directory_allows_old_registration_ranges_but_other_reads_remain_bounded():
    end = datetime.now(UTC) - timedelta(minutes=1)
    data = {"start": end - timedelta(days=3650), "end": end}
    directory = s.UserFiltersSerializer(data=data)
    assert directory.is_valid(), directory.errors
    bounded = s.ReadFiltersSerializer(data=data)
    assert not bounded.is_valid()
    for invalid in ({"start": end, "end": end}, {"end": end + timedelta(days=1)}):
        assert not s.UserFiltersSerializer(data=invalid).is_valid()


def test_all_time_directory_cursor_preserves_snapshot_and_rejects_filter_changes():
    serializer = s.UserFiltersSerializer(data={"limit": 1})
    assert serializer.is_valid()
    filters = serializer.validated_data
    old = datetime.now(UTC) - timedelta(days=400)
    rows = [SimpleNamespace(id=uuid4(), created_at=old) for _ in range(2)]
    queryset = Mock()
    queryset.order_by.return_value = rows
    result = q.page(queryset, filters, "actor:users", lambda row: str(row.id))
    token = result["nextCursor"]
    request = SimpleNamespace(query_params=QueryDict(f"cursor={token}&limit=1"))
    restored = v.filters(request, s.UserFiltersSerializer)
    assert restored["end"] == filters["end"]
    assert "start" not in restored
    assert q.fingerprint(restored) == q.fingerprint(filters)
    assert q.decode_cursor(token)["start"] is None
    with pytest.raises(ValidationError):
        q.page(queryset, {**restored, "verified": True}, "actor:users", str)


def test_cursor_restores_original_window_without_running_a_query():
    end = datetime.now(UTC) - timedelta(minutes=1)
    start = end - timedelta(days=1)
    token = signing.dumps(
        {
            "scope": "actor:users",
            "filters": "digest",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "at": start.isoformat(),
            "id": str(uuid4()),
        },
        salt=q.CURSOR_SALT,
    )
    request = SimpleNamespace(query_params=QueryDict(f"cursor={token}"))
    result = v.filters(request)
    assert result["start"] == start
    assert result["end"] == end


def test_projection_ignores_credentials_and_private_text():
    now = datetime.now(UTC)
    user = SimpleNamespace(
        id=uuid4(),
        email="test@example.com",
        display_name="Name",
        pending_deletion=False,
        suspended_at=None,
        is_active=True,
        email_verified_at=None,
        created_at=now,
        updated_at=now,
        version=1,
        password_hash="SECRET",
        notes="PRIVATE",
    )
    data = s.UserSerializer(q.user_projection(user)).data
    assert "SECRET" not in str(data)
    assert "PRIVATE" not in str(data)
    assert set(data) == {
        "id",
        "email",
        "displayName",
        "lifecycle",
        "emailVerified",
        "createdAt",
        "updatedAt",
        "version",
    }
    job = SimpleNamespace(
        id=uuid4(),
        job_type="auth_email",
        status="dead",
        attempts=3,
        max_attempts=3,
        created_at=now,
        updated_at=now,
        available_at=now,
        last_error="PROVIDER_SECRET",
        payload_json={"token": "SECRET"},
    )
    assert q.job_projection(job)["eligibleActions"] == []
    assert "SECRET" not in str(s.JobSerializer(q.job_projection(job)).data)


@pytest.mark.parametrize("kind", list(q.WORK_MODELS))
def test_private_projection_never_serializes_descriptions_or_snapshots(kind):
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        name="Allowed",
        display_name="Allowed",
        status="ready",
        state="running",
        parent_id=None,
        work_item_id=None,
        focus_plan_id=None,
        created_at=now,
        updated_at=now,
        version=1,
        description="SECRET",
        note="SECRET",
        plan_snapshot_json={"secret": 1},
    )
    result = s.WorkSerializer(q.work_projection(row, kind)).data
    assert result["kind"] == kind
    assert "SECRET" not in str(result)
    assert "snapshot" not in str(result)


def test_sensitive_views_require_fresh_mfa_and_explicit_capabilities():
    assert v.UserWorkView.capability == v.WorkDetailView.capability == "read_private"
    assert v.PrivacyRequestsView.capability == v.PrivacyDetailView.capability == "manage_privacy"
    for cls in (
        v.UserWorkView,
        v.WorkDetailView,
        v.PrivacyRequestsView,
        v.PrivacyDetailView,
        v.StaffView,
        v.RolesView,
    ):
        assert cls.step_up is True
    assert v.UserSearchView.capability == v.UsersView.capability == "view_users"
    assert not v.UserSearchView.writes


def test_work_read_audits_before_returning_content():
    row = SimpleNamespace(id=uuid4(), version=1)
    request = SimpleNamespace()
    with (
        patch.object(v, "filters", return_value={"kind": "project"}),
        patch.object(q, "work_queryset"),
        patch.object(v, "get_object_or_404", return_value=row),
        patch.object(q, "work_projection", return_value={}),
        patch.object(v.audit, "record", side_effect=RuntimeError("audit unavailable")),
        patch.object(v, "respond") as respond,
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            v.WorkDetailView().get(request, row.id)
        respond.assert_not_called()


def test_audit_projection_excludes_free_text_comments_and_changes():
    row = SimpleNamespace(
        id=uuid4(),
        actor_id=None,
        action="users.suspend",
        target_type="users",
        target_id=str(uuid4()),
        created_at=datetime.now(UTC),
        request_id="id",
        outcome="success",
        reason_code="support",
        comment="PRIVATE",
        changes_json={"raw": "SECRET"},
    )
    result = s.AuditSerializer(q.audit_projection(row)).data
    assert "PRIVATE" not in str(result)
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("body", [[], "query", {"cursor": ["invalid"]}])
def test_search_rejects_malformed_body_without_querying(body):
    request = SimpleNamespace(data=body)
    with pytest.raises(ValidationError):
        v.filters(request, s.UserFiltersSerializer, body=True)


def test_private_jobs_require_privacy_step_up_before_querying():
    request = SimpleNamespace(user=SimpleNamespace())
    with (
        patch.object(v, "filters", return_value={"type": "data_export"}),
        patch.object(v, "effective_capabilities", return_value=["manage_privacy", "view_jobs"]),
        patch.object(v, "require_capability", side_effect=RuntimeError("denied")) as require,
        patch.object(q, "jobs") as query,
    ):
        with pytest.raises(RuntimeError, match="denied"):
            v.JobsView().get(request)
        require.assert_called_once_with(request, "manage_privacy", step_up=True)
        query.assert_not_called()


@pytest.mark.parametrize(
    "kind, tag",
    [
        ("project", "work-item"),
        ("sprint", "work-item"),
        ("chore", "work-item"),
        ("work_type", "work-type"),
        ("focus_plan", "focus-plan"),
        ("execution_session", "execution-session"),
    ],
)
def test_work_detail_etag_matches_domain_services(kind, tag):
    row = SimpleNamespace(id=uuid4(), version=7)
    request = SimpleNamespace()
    with (
        patch.object(v, "filters", return_value={"kind": kind}),
        patch.object(q, "work_queryset"),
        patch.object(v, "get_object_or_404", return_value=row),
        patch.object(q, "work_projection", return_value={}),
        patch.object(v.audit, "record"),
        patch.object(v, "respond", return_value={}),
    ):
        response = v.WorkDetailView().get(request, row.id)
    assert response["ETag"] == f'"{tag}:{row.id}:v7"'


def test_audit_changes_are_typed_allowlisted_and_role_scoped():
    raw = {
        "state": "suspended",
        "version": 2,
        "isActive": False,
        "roles": ["Owner"],
        "jobType": "data_export",
        "comment": "SECRET",
        "password": "SECRET",
        "operation": "SECRET",
        "count": "SECRET",
    }
    limited = q.audit_changes(raw)
    assert limited == {"state": "suspended", "version": 2, "isActive": False}
    owner = q.audit_changes(raw, owner=True)
    assert owner["roles"] == ["Owner"]
    assert owner["jobType"] == "data_export"
    assert "SECRET" not in str(s.AuditChangesSerializer(owner).data)
    assert q.audit_changes({"jobType": [], "roles": [{}]}, owner=True) == {"roles": []}


@pytest.mark.parametrize("kind", list(q.WORK_MODELS))
def test_work_detail_fields_are_explicit_and_lists_remain_minimal(kind):
    now = datetime.now(UTC)
    fields = {field: None for field in q.WORK_DETAIL_FIELDS[kind].values()}
    if kind in {"project", "sprint", "chore"}:
        fields.update(
            description="Private work description",
            priority=2,
            work_type_id=uuid4(),
            deadline_at=now,
        )
    elif kind == "work_type":
        fields.update(
            description="Type description",
            slug="reading",
            is_system=False,
            cognitive_demand="high",
            interruption_sensitivity="high",
            continuity_need="high",
            repetitiveness="low",
            physicality="low",
            learning_mode="practice",
        )
    elif kind == "focus_plan":
        fields.update(source="manual", is_template=False)
    else:
        fields.update(
            current_segment_index=2, session_started_at=now, current_segment_started_at=now
        )
    row = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        name="Private name",
        display_name="Private type",
        status="ready",
        state="running",
        parent_id=None,
        work_item_id=uuid4(),
        focus_plan_id=uuid4(),
        created_at=now,
        updated_at=now,
        version=3,
        admin_segments=[],
        plan_snapshot_json={"raw": "SECRET"},
        recommendation_snapshot_json={"raw": "SECRET"},
        work_context_snapshot_json={},
        review=SimpleNamespace(note="SECRET"),
        **fields,
    )
    if kind == "execution_session":
        del row.status
    listing = s.WorkSerializer(q.work_projection(row, kind)).data
    detail = s.WorkSerializer(q.work_projection(row, kind, detail=True)).data
    assert not set(q.WORK_DETAIL_FIELDS[kind]) & set(listing)
    assert set(q.WORK_DETAIL_FIELDS[kind]) <= set(detail)
    assert "SECRET" not in str(detail)
    assert not any("snapshot" in key.lower() or "review" in key.lower() for key in detail)
    if kind in {"project", "sprint", "chore"}:
        assert detail["description"] == "Private work description"
        assert detail["priority"] == 2
        assert detail["workTypeId"] == str(fields["work_type_id"])
        assert detail["dueAt"] == now.isoformat().replace("+00:00", "Z")
    elif kind == "work_type":
        assert detail["cognitiveDemand"] == "high"
    elif kind == "focus_plan":
        assert detail["segments"] == []
        assert "segments" not in listing
    else:
        assert detail["currentSegmentIndex"] == 2
        assert detail["state"] == "running"


def test_segment_projection_has_only_typed_allowlisted_fields():
    row = SimpleNamespace(
        id=uuid4(),
        segment_index=1,
        kind="work",
        duration_mode="fixed",
        target_seconds=1200,
        min_seconds=None,
        max_seconds=None,
        linked_work_item_id=uuid4(),
        optional=False,
        label="Read",
        instructions="EXCLUDED",
        review_note="EXCLUDED",
    )
    data = s.WorkSegmentSerializer(q.segment_projection(row)).data
    assert set(data) == {
        "id",
        "segmentIndex",
        "kind",
        "durationMode",
        "targetSeconds",
        "minSeconds",
        "maxSeconds",
        "linkedWorkItemId",
        "optional",
        "label",
    }
    assert data["targetSeconds"] == 1200
    assert "EXCLUDED" not in str(data)


def test_work_detail_audits_before_building_detailed_projection():
    row = SimpleNamespace(id=uuid4(), version=1)
    request = SimpleNamespace()
    events = []
    with (
        patch.object(v, "filters", return_value={"kind": "chore"}),
        patch.object(q, "work_queryset") as query,
        patch.object(v, "get_object_or_404", return_value=row),
        patch.object(v.audit, "record", side_effect=lambda *a, **kw: events.append("audit")),
        patch.object(
            q, "work_projection", side_effect=lambda *a, **kw: events.append("detail") or {}
        ) as project,
        patch.object(v, "respond", return_value={}),
    ):
        v.WorkDetailView().get(request, row.id)
        query.assert_called_once_with("chore", detail=True)
        project.assert_called_once_with(row, "chore", detail=True)
    assert events == ["audit", "detail"]


def test_direct_privacy_grant_does_not_advertise_retry_authority():
    request = SimpleNamespace(user=SimpleNamespace())
    with (
        patch.object(v, "filters", return_value={}),
        patch.object(v, "effective_capabilities", return_value=["view_jobs", "manage_privacy"]),
        patch.object(v, "require_capability"),
        patch.object(v, "scope", return_value="staff:jobs"),
        patch.object(q, "jobs", return_value={"items": [], "nextCursor": None}) as jobs,
        patch.object(v.audit, "record"),
        patch.object(v, "respond"),
    ):
        v.JobsView().get(request)
    jobs.assert_called_once_with({}, "staff:jobs", include_privacy=True, retry=False)
