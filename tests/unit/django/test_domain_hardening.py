# ruff: noqa: E402
from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
django.setup()

from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.execution_service import DjangoExecutionService
from taskiller.django_api.focus_service import DjangoFocusService
from taskiller.django_api.portable_views import PortableImportView
from taskiller.django_api.work_service import DjangoWorkService


@pytest.mark.parametrize("service", [DjangoExecutionService, DjangoFocusService])
@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        {"0": "x", "1": "y"},
        None,
        1,
        [1, 2],
        ["x"],
        ["x", "y", "z"],
        ["2026-11-18T00:00:00", str(uuid4())],
    ],
)
def test_sequence_cursors_reject_invalid_structure(service, value):
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(TaskillerAPIError) as error:
        service._decode_cursor(cursor)
    assert (error.value.status_code, error.value.code) == (422, "invalid_cursor")


def test_work_cursor_rejects_extra_fields():
    value = {"createdAt": datetime.now(UTC).isoformat(), "id": str(uuid4()), "extra": 1}
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(TaskillerAPIError) as error:
        DjangoWorkService._decode_cursor(cursor)
    assert error.value.code == "invalid_cursor"


def test_portable_schema_requires_bounded_idempotency_key():
    schema = PortableImportView.post.kwargs["schema"]()
    schema.view = PortableImportView()
    schema.view.request = None
    schema.view.kwargs = {}
    parameters = schema.get_override_parameters()
    header = next(parameter for parameter in parameters if parameter.name == "Idempotency-Key")
    assert header.required
    assert header.location == "header"
    assert header.type == {"type": "string", "minLength": 8, "maxLength": 200}


@pytest.mark.parametrize(
    "method,args",
    [
        ("create_work_item", (None, "test-key")),
        ("update_work_item", (None, None, None)),
        ("delete_work_item", (None, None)),
        ("reorder_work_item", (None, None, None, "test-key")),
        ("delete_work_type", (None, None)),
    ],
)
def test_work_mutations_lock_owner_before_domain_rows(monkeypatch, method, args):
    from contextlib import nullcontext
    from unittest.mock import MagicMock

    from taskiller.django_api import work_service

    class OwnerLocked(Exception):
        pass

    owner = MagicMock()
    owner.select_for_update.return_value.get.side_effect = OwnerLocked
    monkeypatch.setattr(work_service.TaskillerUser, "objects", owner)
    for model in (work_service.WorkItem, work_service.WorkType):
        manager = MagicMock()
        manager.select_for_update.side_effect = AssertionError("domain row locked before owner")
        manager.filter.side_effect = AssertionError("domain read before owner")
        monkeypatch.setattr(model, "objects", manager)
    monkeypatch.setattr(work_service.transaction, "atomic", nullcontext)
    monkeypatch.setattr(work_service, "claim_idempotency", lambda **kwargs: None)
    monkeypatch.setattr(work_service, "_dump", lambda payload: {})
    service = DjangoWorkService.__new__(DjangoWorkService)
    service.owner_id = uuid4()
    service.idempotency_ttl_hours = 24
    with pytest.raises(OwnerLocked):
        call_args = tuple(MagicMock() if arg is None else arg for arg in args)
        getattr(service, method)(*call_args)


@pytest.mark.parametrize("state", ["running", "paused"])
def test_start_rejects_existing_open_session_before_target_lookup(monkeypatch, state):
    from contextlib import nullcontext
    from unittest.mock import MagicMock

    from taskiller.django_api import execution_service
    from taskiller.execution.schemas import StartExecutionSessionRequest

    manager = MagicMock()
    manager.filter.return_value.exists.return_value = True
    monkeypatch.setattr(execution_service.ExecutionSession, "objects", manager)
    monkeypatch.setattr(execution_service.TaskillerUser, "objects", MagicMock())
    work = MagicMock()
    work.select_for_update.side_effect = AssertionError("target lookup before open-session check")
    monkeypatch.setattr(execution_service.WorkItem, "objects", work)
    monkeypatch.setattr(execution_service.transaction, "atomic", nullcontext)
    monkeypatch.setattr(execution_service, "claim_idempotency", lambda **kwargs: None)
    service = DjangoExecutionService.__new__(DjangoExecutionService)
    service.owner_id = uuid4()
    service.idempotency_ttl_hours = 24
    payload = StartExecutionSessionRequest(work_item_id=uuid4(), focus_plan_id=uuid4())
    with pytest.raises(TaskillerAPIError) as error:
        service.start_session(payload, "test-key")
    assert (error.value.status_code, error.value.code) == (409, "open_session_exists")
    assert state in manager.filter.call_args.kwargs["state__in"]


@pytest.mark.parametrize(
    "invalid", ["missing", "foreign", "wrong_kind", "wrong_chore", "wrong_parent", "terminal"]
)
def test_segment_validation_rejects_invalid_work(monkeypatch, invalid):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from taskiller.django_api import execution_service

    target_id, linked_id = uuid4(), uuid4()
    target = SimpleNamespace(id=target_id, kind="sprint" if invalid != "wrong_chore" else "chore")
    row = SimpleNamespace(
        id=linked_id,
        kind="sprint" if invalid == "wrong_kind" else "chore",
        parent_id=uuid4() if invalid == "wrong_parent" else target_id,
        status="completed" if invalid == "terminal" else "ready",
    )
    manager = MagicMock()
    manager.select_for_update.return_value.filter.return_value.order_by.return_value = (
        [] if invalid in {"missing", "foreign"} else [row]
    )
    monkeypatch.setattr(execution_service.WorkItem, "objects", manager)
    service = DjangoExecutionService.__new__(DjangoExecutionService)
    service.owner_id = uuid4()
    with pytest.raises(TaskillerAPIError) as error:
        service._validate_segment_work_items(
            target, [SimpleNamespace(linked_work_item_id=linked_id)]
        )
    assert error.value.code == (
        "work_item_terminal" if invalid == "terminal" else "invalid_focus_plan_link"
    )
    filters = manager.select_for_update.return_value.filter.call_args.kwargs
    assert filters["owner_id"] == service.owner_id
    assert filters["deleted_at__isnull"]


@pytest.mark.parametrize(
    "initial,expected",
    [("draft", ["ready", "in_progress"]), ("ready", ["in_progress"]), ("in_progress", [])],
)
def test_session_start_persists_each_work_state_transition(initial, expected):
    from types import SimpleNamespace
    from unittest.mock import Mock

    now = datetime.now(UTC)
    persisted = initial
    writes = []
    row = SimpleNamespace(status=initial, version=1, updated_at=None)

    def save():
        nonlocal persisted
        allowed = {"draft": {"ready"}, "ready": {"in_progress"}}
        assert row.status in allowed.get(persisted, set()), "invalid work item state transition"
        persisted = row.status
        writes.append(row.status)

    row.save = Mock(side_effect=save)
    service = DjangoExecutionService.__new__(DjangoExecutionService)
    service._move_work_item_to_in_progress(row, now)
    assert writes == expected
    assert row.version == 1 + len(expected)
    if expected:
        assert row.updated_at == now
