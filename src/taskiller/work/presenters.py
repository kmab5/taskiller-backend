from taskiller.work.models import WorkItem, WorkType
from taskiller.work.schemas import (
    IntensityLevel,
    LearningMode,
    PartialWorkCharacteristics,
    PhysicalityLevel,
    WorkCharacteristics,
    WorkItemKind,
    WorkItemResponse,
    WorkItemStatus,
    WorkTypeResponse,
)

_CHARACTERISTIC_FIELDS = (
    "cognitive_demand",
    "interruption_sensitivity",
    "continuity_need",
    "repetitiveness",
    "physicality",
    "learning_mode",
)


def characteristics_from_work_type(work_type: WorkType) -> WorkCharacteristics:
    return WorkCharacteristics(
        cognitive_demand=IntensityLevel(work_type.cognitive_demand),
        interruption_sensitivity=IntensityLevel(work_type.interruption_sensitivity),
        continuity_need=IntensityLevel(work_type.continuity_need),
        repetitiveness=IntensityLevel(work_type.repetitiveness),
        physicality=PhysicalityLevel(work_type.physicality),
        learning_mode=LearningMode(work_type.learning_mode),
    )


def work_type_to_response(work_type: WorkType) -> WorkTypeResponse:
    return WorkTypeResponse(
        id=work_type.id,
        slug=work_type.slug,
        display_name=work_type.display_name,
        description=work_type.description,
        characteristics=characteristics_from_work_type(work_type),
        system=work_type.is_system,
        version=work_type.version,
    )


def work_item_overrides(work_item: WorkItem) -> PartialWorkCharacteristics | None:
    values = {
        field: getattr(work_item, f"{field}_override")
        for field in _CHARACTERISTIC_FIELDS
        if getattr(work_item, f"{field}_override") is not None
    }
    if not values:
        return None
    return PartialWorkCharacteristics.model_validate(values)


def effective_characteristics(
    work_item: WorkItem,
    work_type: WorkType | None,
) -> WorkCharacteristics | None:
    values: dict[str, str] = {}
    if work_type is not None:
        values = {field: str(getattr(work_type, field)) for field in _CHARACTERISTIC_FIELDS}
    for field in _CHARACTERISTIC_FIELDS:
        override = getattr(work_item, f"{field}_override")
        if override is not None:
            values[field] = str(override)
    if len(values) != len(_CHARACTERISTIC_FIELDS):
        return None
    return WorkCharacteristics.model_validate(values)


def work_item_to_response(
    work_item: WorkItem,
    work_type: WorkType | None = None,
) -> WorkItemResponse:
    return WorkItemResponse(
        id=work_item.id,
        kind=WorkItemKind(work_item.kind),
        parent_id=work_item.parent_id,
        work_type_id=work_item.work_type_id,
        name=work_item.name,
        description=work_item.description,
        status=WorkItemStatus(work_item.status),
        position=work_item.position,
        priority=work_item.priority,
        estimated_effort_seconds=work_item.estimated_effort_seconds,
        planned_start_at=work_item.planned_start_at,
        deadline_at=work_item.deadline_at,
        target_start_date=work_item.target_start_date,
        target_end_date=work_item.target_end_date,
        characteristic_overrides=work_item_overrides(work_item),
        effective_characteristics=effective_characteristics(work_item, work_type),
        completed_at=work_item.completed_at,
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
        deleted_at=work_item.deleted_at,
        version=work_item.version,
    )
