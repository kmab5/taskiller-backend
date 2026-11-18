from __future__ import annotations

import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import Client

from taskiller.django_domain.models import (
    ExecutionSession,
    FocusPlan,
    FocusPlanSegment,
    SecurityEvent,
    SessionEvent,
    TaskillerUser,
    WorkItem,
    WorkType,
)

pytestmark = pytest.mark.integration


def clone_row(row, **overrides):
    values = {field.attname: getattr(row, field.attname) for field in row._meta.local_fields}
    values.update(id=uuid4(), **overrides)
    return type(row).objects.create(**values)


@pytest.fixture
def graph():
    client = Client()
    registration = client.post(
        "/api/v1/auth/register",
        {"email": f"schema-{uuid4().hex}@example.com", "password": "Schema-test-password-123"},
        content_type="application/json",
    )
    assert registration.status_code == 201, registration.content
    auth = {"HTTP_AUTHORIZATION": f"Bearer {registration.json()['accessToken']}"}
    chore = client.post(
        "/api/v1/work-items",
        {"kind": "chore", "name": "Schema chore", "status": "ready"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"schema-work-{uuid4().hex}",
        **auth,
    )
    assert chore.status_code == 201, chore.content
    plan = client.post(
        "/api/v1/focus-plans",
        {
            "workItemId": chore.json()["id"],
            "source": "manual",
            "name": "Schema plan",
            "template": False,
            "segments": [{"kind": "work", "durationMode": "fixed", "targetSeconds": 60}],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"schema-plan-{uuid4().hex}",
        **auth,
    )
    assert plan.status_code == 201, plan.content
    session = client.post(
        "/api/v1/execution-sessions",
        {"workItemId": chore.json()["id"], "focusPlanId": plan.json()["id"]},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"schema-start-{uuid4().hex}",
        **auth,
    )
    assert session.status_code == 201, session.content
    return {
        "user": TaskillerUser.objects.get(id=registration.json()["user"]["id"]),
        "work": WorkItem.objects.get(id=chore.json()["id"]),
        "session": ExecutionSession.objects.get(id=session.json()["id"]),
    }


def test_database_rejects_case_insensitive_duplicate_email(graph):
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(graph["user"], email=graph["user"].email.upper())


def test_database_rejects_second_open_session(graph):
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(graph["session"])


def test_database_rejects_duplicate_system_work_type():
    system_type = WorkType.objects.filter(is_system=True).first()
    assert system_type is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(system_type, slug=system_type.slug.upper())


def test_database_rejects_invalid_work_kind(graph):
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(graph["work"], kind="invalid")


def test_database_rejects_cross_owner_parent(graph):
    other = clone_row(graph["user"], email=f"other-{uuid4().hex}@example.com")
    project = clone_row(graph["work"], kind="project", owner_id=other.id)
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(graph["work"], parent_id=project.id)


def test_database_rejects_cross_owner_session(graph):
    other = clone_row(graph["user"], email=f"other-{uuid4().hex}@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(graph["session"], owner_id=other.id)


def test_database_rejects_linked_item_on_generic_template(graph):
    source = FocusPlan.objects.get(id=graph["session"].focus_plan_id)
    template = clone_row(source, work_item_id=None, recommendation_id=None, is_template=True)
    segment = FocusPlanSegment.objects.filter(focus_plan=source).first()
    assert segment is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        clone_row(segment, focus_plan_id=template.id, linked_work_item_id=graph["work"].id)


def test_security_events_are_append_only(graph):
    event = SecurityEvent.objects.filter(user_id=graph["user"].id).first()
    assert event is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        SecurityEvent.objects.filter(id=event.id).delete()


def test_session_events_are_append_only(graph):
    event = SessionEvent.objects.filter(session=graph["session"]).first()
    assert event is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        SessionEvent.objects.filter(id=event.id).update(type="changed")


def test_baseline_audit_detects_missing_unique_index():
    audit = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts" / "django_phase9_baseline_audit.py")
    )
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX tk_users_email_ci_unique")
    with pytest.raises(SystemExit, match="tk_users_email_ci_unique"):
        audit["main"]()


def test_baseline_audit_detects_missing_ownership_trigger():
    audit = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts" / "django_phase9_baseline_audit.py")
    )
    with connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER tk_work_items_relationships ON work_items")
    with pytest.raises(SystemExit, match="tk_work_items_relationships"):
        audit["main"]()
