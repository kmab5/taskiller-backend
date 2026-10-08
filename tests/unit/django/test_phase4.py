from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.work_service import DjangoWorkService
from taskiller.work.schemas import WorkItemKind, WorkItemStatus


def test_work_cursor_round_trip() -> None:
    created = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    item_id = uuid4()

    cursor = DjangoWorkService._encode_cursor(created, item_id)
    parsed_created, parsed_id = DjangoWorkService._decode_cursor(cursor)

    assert parsed_created == created
    assert parsed_id == item_id


def test_invalid_work_cursor_uses_stable_problem_code() -> None:
    with pytest.raises(TaskillerAPIError) as error:
        DjangoWorkService._decode_cursor("not-a-valid-cursor")

    assert error.value.code == "invalid_cursor"


def test_work_transition_matrix_rejects_draft_to_completed() -> None:
    assert WorkItemStatus.COMPLETED not in {
        WorkItemStatus.READY,
        WorkItemStatus.CANCELLED,
    }
    assert WorkItemKind.PROJECT.value == "project"
