from datetime import UTC, datetime
from uuid import uuid4

from taskiller.work.models import WorkItem, WorkType
from taskiller.work.presenters import work_item_to_response


def test_effective_characteristics_overlay_task_overrides_on_work_type() -> None:
    now = datetime.now(UTC)
    work_type = WorkType(
        id=uuid4(),
        owner_id=None,
        slug="programming",
        display_name="Programming",
        description=None,
        cognitive_demand="high",
        interruption_sensitivity="high",
        continuity_need="high",
        repetitiveness="low",
        physicality="sedentary",
        learning_mode="none",
        is_system=True,
        created_at=now,
        updated_at=now,
        version=1,
    )
    item = WorkItem(
        id=uuid4(),
        owner_id=uuid4(),
        kind="chore",
        parent_id=None,
        work_type_id=work_type.id,
        name="Implement API",
        description=None,
        status="ready",
        position=1024,
        priority=None,
        estimated_effort_seconds=3600,
        planned_start_at=None,
        deadline_at=None,
        target_start_date=None,
        target_end_date=None,
        cognitive_demand_override=None,
        interruption_sensitivity_override="medium",
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

    response = work_item_to_response(item, work_type)

    assert response.characteristic_overrides is not None
    assert response.characteristic_overrides.interruption_sensitivity == "medium"
    assert response.effective_characteristics is not None
    assert response.effective_characteristics.cognitive_demand == "high"
    assert response.effective_characteristics.interruption_sensitivity == "medium"
