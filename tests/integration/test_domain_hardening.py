# ruff: noqa: E402
from __future__ import annotations

import os
from uuid import UUID, uuid4

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
django.setup()

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.execution_service import DjangoExecutionService
from taskiller.django_api.focus_service import DjangoFocusService
from taskiller.django_api.work_service import DjangoWorkService
from taskiller.django_domain.models import ExecutionSession, TaskillerUser, WorkItem
from taskiller.execution.schemas import StartExecutionSessionRequest
from taskiller.focus.schemas import CreateFocusPlanRequest
from taskiller.users.etag import make_etag
from taskiller.work.schemas import CreateWorkItemRequest, CreateWorkTypeRequest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated_service_settings(monkeypatch):
    from taskiller.core.config import Settings
    from taskiller.django_api import execution_service, focus_service, work_service

    settings = Settings(_env_file=None)
    for module in (execution_service, focus_service, work_service):
        monkeypatch.setattr(module, "taskiller_settings", lambda: settings)


def owner():
    now = utc_now()
    return TaskillerUser.objects.create(
        id=uuid4(),
        email=f"{uuid4()}@example.test",
        password_hash="unused",
        password_changed_at=now,
        is_active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )


def item(user, kind="chore", parent=None, **kwargs):
    result = DjangoWorkService(user.id).create_work_item(
        CreateWorkItemRequest(kind=kind, name="Test work", parent_id=parent, **kwargs),
        str(uuid4()),
    )
    return WorkItem.objects.get(id=result["id"])


def plan(user, target, linked=None):
    result = DjangoFocusService(user.id).create_focus_plan(
        CreateFocusPlanRequest.model_validate(
            {
                "workItemId": str(target.id),
                "source": "manual",
                "name": "Test plan",
                "segments": [
                    {
                        "kind": "work",
                        "durationMode": "fixed",
                        "targetSeconds": 60,
                        "linkedWorkItemId": str(linked.id) if linked else None,
                    }
                ],
            }
        ),
        str(uuid4()),
    )
    return UUID(result["id"])


def test_delete_work_type_detaches_live_and_deleted_items_with_versions():
    user = owner()
    service = DjangoWorkService(user.id)
    result = service.create_work_type(
        CreateWorkTypeRequest.model_validate(
            {
                "slug": "custom",
                "displayName": "Custom",
                "characteristics": {
                    "cognitiveDemand": "medium",
                    "interruptionSensitivity": "medium",
                    "continuityNeed": "medium",
                    "repetitiveness": "medium",
                    "physicality": "sedentary",
                    "learningMode": "none",
                },
            }
        ),
        str(uuid4()),
    )
    rows = [item(user, work_type_id=UUID(result["id"])) for _ in range(2)]
    WorkItem.objects.filter(id=rows[1].id).update(deleted_at=utc_now())
    service.delete_work_type(UUID(result["id"]), make_etag("work-type", result["id"], 1))
    for row in rows:
        previous_updated = row.updated_at
        row.refresh_from_db()
        assert row.work_type_id is None
        assert row.version == 2
        assert row.updated_at > previous_updated


@pytest.mark.parametrize("change", ["deleted", "moved", "completed", "cancelled", "archived"])
def test_start_revalidates_linked_sprint_chore(change):
    user = owner()
    project = item(user, "project")
    sprint = item(user, "sprint", project.id)
    chore = item(user, parent=sprint.id)
    focus_plan_id = plan(user, sprint, chore)
    changes = (
        {"deleted_at": utc_now()}
        if change == "deleted"
        else ({"parent_id": project.id} if change == "moved" else {"status": change})
    )
    WorkItem.objects.filter(id=chore.id).update(**changes)
    with pytest.raises(TaskillerAPIError) as error:
        DjangoExecutionService(user.id).start_session(
            StartExecutionSessionRequest(work_item_id=sprint.id, focus_plan_id=focus_plan_id),
            str(uuid4()),
        )
    expected = (
        "work_item_terminal"
        if change in {"completed", "cancelled", "archived"}
        else "invalid_focus_plan_link"
    )
    assert error.value.code == expected
    assert not ExecutionSession.objects.filter(owner_id=user.id).exists()


@pytest.mark.parametrize("state", ["running", "paused"])
def test_start_second_session_conflicts_and_replay_succeeds(state):
    user = owner()
    chore = item(user)
    focus_plan_id = plan(user, chore, chore)
    service = DjangoExecutionService(user.id)
    payload = StartExecutionSessionRequest(work_item_id=chore.id, focus_plan_id=focus_plan_id)
    key = str(uuid4())
    first = service.start_session(payload, key)
    if state == "paused":
        ExecutionSession.objects.filter(id=first["id"]).update(state=state, paused_at=utc_now())
    assert service.start_session(payload, key) == first
    with pytest.raises(TaskillerAPIError) as error:
        service.start_session(payload, str(uuid4()))
    assert error.value.code == "open_session_exists"
    assert ExecutionSession.objects.filter(owner_id=user.id).count() == 1


@pytest.mark.parametrize("operation", ["create", "move", "reorder", "start"])
def test_domain_writes_lock_owner_before_work_namespace(operation):
    from django.db import connection

    from taskiller.work.schemas import ReorderWorkItemRequest, UpdateWorkItemRequest

    user = owner()
    project = item(user, "project")
    sprint = item(user, "sprint", project.id)
    chore = item(user, parent=project.id)
    focus_plan_id = plan(user, chore)
    locks = []

    def record_locks(execute, sql, params, many, context):
        if "FOR UPDATE" in sql:
            locks.append(sql)
        return execute(sql, params, many, context)

    service = DjangoWorkService(user.id)
    with connection.execute_wrapper(record_locks):
        if operation == "create":
            item(user, parent=sprint.id)
        elif operation == "move":
            service.update_work_item(
                chore.id,
                UpdateWorkItemRequest(parent_id=sprint.id),
                make_etag("work-item", chore.id, chore.version),
            )
        elif operation == "reorder":
            service.reorder_work_item(
                chore.id,
                ReorderWorkItemRequest(),
                make_etag("work-item", chore.id, chore.version),
                str(uuid4()),
            )
        else:
            DjangoExecutionService(user.id).start_session(
                StartExecutionSessionRequest(work_item_id=chore.id, focus_plan_id=focus_plan_id),
                str(uuid4()),
            )
    assert locks
    assert 'FROM "users"' in locks[0]


def test_concurrent_sibling_reorders_complete_without_deadlock():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections, transaction

    from taskiller.django_domain.models import IdempotencyRecord
    from taskiller.work.schemas import ReorderWorkItemRequest

    # Thread connections need committed seed rows, unlike the surrounding rollback
    # fixture. Keep this dataset isolated and remove it explicitly in finally.
    def seed():
        try:
            with transaction.atomic():
                user = owner()
                project = item(user, "project")
                children = [item(user, parent=project.id) for _ in range(3)]
                return user.id, [child.id for child in children]
        finally:
            connections.close_all()

    gate = Barrier(2)

    def reorder(user_id, selected_id, anchor_id):
        try:
            with transaction.atomic():
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    cursor.execute("SET LOCAL statement_timeout = '10s'")
                gate.wait(timeout=5)
                return DjangoWorkService(user_id).reorder_work_item(
                    selected_id,
                    ReorderWorkItemRequest(before_id=anchor_id),
                    make_etag("work-item", selected_id, 1),
                    str(uuid4()),
                )
        finally:
            connections.close_all()

    def cleanup(user_id):
        try:
            with transaction.atomic():
                IdempotencyRecord.objects.filter(owner_id=user_id).delete()
                WorkItem.objects.filter(owner_id=user_id).delete()
                TaskillerUser.objects.filter(id=user_id).delete()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        user_id, child_ids = pool.submit(seed).result(timeout=15)
        try:
            futures = [
                pool.submit(reorder, user_id, child_id, child_ids[2]) for child_id in child_ids[:2]
            ]
            results = [future.result(timeout=15) for future in futures]
            assert {result["id"] for result in results} == {str(value) for value in child_ids[:2]}
            positions = list(
                WorkItem.objects.filter(id__in=child_ids).values_list("position", flat=True)
            )
            assert len(set(positions)) == 3
        finally:
            pool.submit(cleanup, user_id).result(timeout=15)
