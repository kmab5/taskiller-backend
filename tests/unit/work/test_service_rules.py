from datetime import UTC, datetime
from uuid import uuid4

import pytest

from taskiller.core.problems import ApiError
from taskiller.work.models import WorkItem
from taskiller.work.schemas import WorkItemStatus
from taskiller.work.service import WorkService


def _item(status: str) -> WorkItem:
    now = datetime.now(UTC)
    return WorkItem(
        id=uuid4(),
        owner_id=uuid4(),
        kind="chore",
        parent_id=None,
        work_type_id=None,
        name="Task",
        description=None,
        status=status,
        position=1024,
        priority=None,
        estimated_effort_seconds=None,
        planned_start_at=None,
        deadline_at=None,
        target_start_date=None,
        target_end_date=None,
        cognitive_demand_override=None,
        interruption_sensitivity_override=None,
        continuity_need_override=None,
        repetitiveness_override=None,
        physicality_override=None,
        learning_mode_override=None,
        completed_at=None,
        cancelled_at=None,
        archived_at=None,
        deleted_at=None,
        created_at=now,
        updated_at=now,
        version=1,
    )


def test_ready_can_complete_and_sets_completion_timestamp() -> None:
    item = _item("ready")
    WorkService._transition_status(item, WorkItemStatus.COMPLETED)
    assert item.status == "completed"
    assert item.completed_at is not None


def test_completed_cannot_jump_directly_to_in_progress() -> None:
    item = _item("completed")
    with pytest.raises(ApiError) as caught:
        WorkService._transition_status(item, WorkItemStatus.IN_PROGRESS)
    assert caught.value.code == "work_item_state_conflict"


def test_cursor_round_trip() -> None:
    created_at = datetime.now(UTC)
    item_id = uuid4()
    cursor = WorkService._encode_cursor(created_at, item_id)
    decoded_at, decoded_id = WorkService._decode_cursor(cursor)
    assert decoded_at == created_at
    assert decoded_id == item_id
