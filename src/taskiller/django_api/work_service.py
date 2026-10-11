from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from pydantic import BaseModel, ValidationError

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.idempotency import (
    claim_idempotency,
    complete_idempotency,
)
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import TaskillerUser, WorkItem, WorkType
from taskiller.users.etag import make_etag
from taskiller.work.presenters import work_item_to_response, work_type_to_response
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    CreateWorkTypeRequest,
    PartialWorkCharacteristics,
    ReorderWorkItemRequest,
    UpdateWorkItemRequest,
    UpdateWorkTypeRequest,
    WorkItemKind,
    WorkItemStatus,
)

_POSITION_STEP = 1024
_CHARACTERISTIC_FIELDS = (
    "cognitive_demand",
    "interruption_sensitivity",
    "continuity_need",
    "repetitiveness",
    "physicality",
    "learning_mode",
)
_TERMINAL_STATUSES = {
    WorkItemStatus.COMPLETED,
    WorkItemStatus.CANCELLED,
    WorkItemStatus.ARCHIVED,
}
_ACTIONABLE_STATUSES = {WorkItemStatus.READY, WorkItemStatus.IN_PROGRESS}
_ALLOWED_TRANSITIONS: dict[WorkItemStatus, set[WorkItemStatus]] = {
    WorkItemStatus.DRAFT: {WorkItemStatus.READY, WorkItemStatus.CANCELLED},
    WorkItemStatus.READY: {
        WorkItemStatus.IN_PROGRESS,
        WorkItemStatus.COMPLETED,
        WorkItemStatus.CANCELLED,
        WorkItemStatus.ARCHIVED,
    },
    WorkItemStatus.IN_PROGRESS: {
        WorkItemStatus.COMPLETED,
        WorkItemStatus.CANCELLED,
    },
    WorkItemStatus.COMPLETED: {
        WorkItemStatus.READY,
        WorkItemStatus.ARCHIVED,
    },
    WorkItemStatus.CANCELLED: {
        WorkItemStatus.READY,
        WorkItemStatus.ARCHIVED,
    },
    WorkItemStatus.ARCHIVED: {WorkItemStatus.READY},
}


def validate_payload[T: BaseModel](model: type[T], data: Any) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors: list[dict[str, object]] = []
        for item in exc.errors():
            errors.append(
                {
                    "type": item.get("type"),
                    "loc": ["body", *item.get("loc", ())],
                    "msg": item.get("msg"),
                }
            )
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "One or more request values are invalid.",
            meta={"errors": errors},
        ) from exc


def require_idempotency_key(value: str | None) -> str:
    key = value or ""
    if not 8 <= len(key) <= 200:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "One or more request values are invalid.",
        )
    return key


def require_etag(if_match: str | None, expected: str) -> None:
    if if_match is None or if_match.strip() != expected:
        raise TaskillerAPIError(
            412,
            "precondition_failed",
            "Resource version mismatch",
            "Refresh the resource and retry using its latest ETag.",
            headers={"ETag": expected},
        )


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


def _work_type_response(row: WorkType) -> dict[str, Any]:
    return _dump(work_type_to_response(row))  # type: ignore[arg-type]


def _work_item_response(
    row: WorkItem,
    work_type: WorkType | None = None,
) -> dict[str, Any]:
    return _dump(work_item_to_response(row, work_type))  # type: ignore[arg-type]


class DjangoWorkService:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.idempotency_ttl_hours = taskiller_settings().idempotency_ttl_hours

    def list_work_types(self) -> dict[str, object]:
        rows = list(
            WorkType.objects.filter(Q(owner_id__isnull=True) | Q(owner_id=self.owner_id)).order_by(
                "-is_system", "display_name", "id"
            )
        )
        return {"items": [_work_type_response(row) for row in rows]}

    def create_work_type(
        self,
        payload: CreateWorkTypeRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope = "work-types:create"
        request_body = _dump(payload)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            if WorkType.objects.filter(
                owner_id=self.owner_id,
                slug__iexact=payload.slug,
            ).exists():
                raise self._slug_conflict()

            now = utc_now()
            row = WorkType(
                id=uuid4(),
                owner_id=self.owner_id,
                slug=payload.slug,
                display_name=payload.display_name,
                description=payload.description,
                cognitive_demand=payload.characteristics.cognitive_demand.value,
                interruption_sensitivity=(payload.characteristics.interruption_sensitivity.value),
                continuity_need=payload.characteristics.continuity_need.value,
                repetitiveness=payload.characteristics.repetitiveness.value,
                physicality=payload.characteristics.physicality.value,
                learning_mode=payload.characteristics.learning_mode.value,
                is_system=False,
                created_at=now,
                updated_at=now,
                version=1,
            )
            try:
                row.save(force_insert=True)
            except IntegrityError as exc:
                raise self._slug_conflict() from exc

            response = _work_type_response(row)
            complete_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                response_status=201,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_work_type(self, work_type_id: UUID) -> dict[str, Any]:
        row = self._available_work_type(work_type_id)
        if row is None:
            raise self._work_type_not_found()
        return _work_type_response(row)

    def update_work_type(
        self,
        work_type_id: UUID,
        payload: UpdateWorkTypeRequest,
        if_match: str | None,
    ) -> dict[str, Any]:
        with transaction.atomic():
            row = (
                WorkType.objects.select_for_update()
                .filter(id=work_type_id)
                .filter(Q(owner_id__isnull=True) | Q(owner_id=self.owner_id))
                .first()
            )
            if row is None:
                raise self._work_type_not_found()
            if row.is_system:
                raise self._system_work_type_immutable()

            require_etag(
                if_match,
                make_etag("work-type", row.id, row.version),
            )
            changed = False

            if "display_name" in payload.model_fields_set:
                assert payload.display_name is not None
                if row.display_name != payload.display_name:
                    row.display_name = payload.display_name
                    changed = True

            if "description" in payload.model_fields_set and row.description != payload.description:
                row.description = payload.description
                changed = True

            if (
                "characteristics" in payload.model_fields_set
                and payload.characteristics is not None
            ):
                values = {
                    "cognitive_demand": payload.characteristics.cognitive_demand.value,
                    "interruption_sensitivity": (
                        payload.characteristics.interruption_sensitivity.value
                    ),
                    "continuity_need": payload.characteristics.continuity_need.value,
                    "repetitiveness": payload.characteristics.repetitiveness.value,
                    "physicality": payload.characteristics.physicality.value,
                    "learning_mode": payload.characteristics.learning_mode.value,
                }
                for field, value in values.items():
                    if getattr(row, field) != value:
                        setattr(row, field, value)
                        changed = True

            if changed:
                row.version += 1
                row.updated_at = utc_now()
                row.save()

            return _work_type_response(row)

    def delete_work_type(
        self,
        work_type_id: UUID,
        if_match: str | None,
    ) -> None:
        with transaction.atomic():
            row = (
                WorkType.objects.select_for_update()
                .filter(id=work_type_id)
                .filter(Q(owner_id__isnull=True) | Q(owner_id=self.owner_id))
                .first()
            )
            if row is None:
                raise self._work_type_not_found()
            if row.is_system:
                raise self._system_work_type_immutable()
            require_etag(
                if_match,
                make_etag("work-type", row.id, row.version),
            )
            row.delete()

    def list_work_items(
        self,
        *,
        limit: int,
        cursor: str | None,
        kind: WorkItemKind | None,
        status: WorkItemStatus | None,
        parent_id: UUID | None,
        include_deleted: bool,
    ) -> dict[str, object]:
        query = WorkItem.objects.filter(owner_id=self.owner_id)

        if not include_deleted:
            query = query.filter(deleted_at__isnull=True)
        if kind is not None:
            query = query.filter(kind=kind.value)
        if status is not None:
            query = query.filter(status=status.value)
        if parent_id is not None:
            query = query.filter(parent_id=parent_id)
        if cursor is not None:
            cursor_time, cursor_id = self._decode_cursor(cursor)
            query = query.filter(
                Q(created_at__lt=cursor_time) | Q(created_at=cursor_time, id__lt=cursor_id)
            )

        rows = list(query.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = None
        if has_more and page_rows:
            tail = page_rows[-1]
            next_cursor = self._encode_cursor(tail.created_at, tail.id)

        return {
            "items": self._item_responses(page_rows),
            "page": {
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
        }

    def create_work_item(
        self,
        payload: CreateWorkItemRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope = "work-items:create"
        request_body = _dump(payload)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            self._validate_hierarchy(
                payload.kind,
                payload.parent_id,
            )
            work_type = self._validate_work_type_reference(payload.work_type_id)
            self._validate_work_item_dates(
                payload.kind,
                payload.planned_start_at,
                payload.deadline_at,
                payload.target_start_date,
                payload.target_end_date,
            )

            now = utc_now()
            position = self._next_position(payload.parent_id)
            completed_at, cancelled_at, archived_at = self._initial_terminal_timestamps(
                payload.status, now
            )
            row = WorkItem(
                id=uuid4(),
                owner_id=self.owner_id,
                kind=payload.kind.value,
                parent_id=payload.parent_id,
                work_type_id=(work_type.id if work_type is not None else None),
                name=payload.name,
                description=payload.description,
                status=payload.status.value,
                position=position,
                priority=payload.priority,
                estimated_effort_seconds=payload.estimated_effort_seconds,
                planned_start_at=payload.planned_start_at,
                deadline_at=payload.deadline_at,
                target_start_date=payload.target_start_date,
                target_end_date=payload.target_end_date,
                completed_at=completed_at,
                cancelled_at=cancelled_at,
                archived_at=archived_at,
                deleted_at=None,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._replace_overrides(row, payload.characteristic_overrides)
            row.save(force_insert=True)

            response = _work_item_response(row, work_type)
            complete_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                response_status=201,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_work_item(self, work_item_id: UUID) -> dict[str, Any]:
        row = self._live_work_item(work_item_id)
        if row is None:
            raise self._work_item_not_found()
        work_type = self._available_work_type(row.work_type_id) if row.work_type_id else None
        return _work_item_response(row, work_type)

    def update_work_item(
        self,
        work_item_id: UUID,
        payload: UpdateWorkItemRequest,
        if_match: str | None,
    ) -> dict[str, Any]:
        with transaction.atomic():
            row = self._locked_live_work_item(work_item_id)
            if row is None:
                raise self._work_item_not_found()

            require_etag(
                if_match,
                make_etag("work-item", row.id, row.version),
            )

            changed = False

            if "parent_id" in payload.model_fields_set and payload.parent_id != row.parent_id:
                self._validate_hierarchy(
                    WorkItemKind(row.kind),
                    payload.parent_id,
                    row.id,
                )
                row.parent_id = payload.parent_id
                row.position = self._next_position(
                    payload.parent_id,
                    exclude_id=row.id,
                )
                changed = True

            if "work_type_id" in payload.model_fields_set:
                work_type = self._validate_work_type_reference(payload.work_type_id)
                new_id = work_type.id if work_type is not None else None
                if row.work_type_id != new_id:
                    row.work_type_id = new_id
                    changed = True
            else:
                work_type = (
                    self._available_work_type(row.work_type_id) if row.work_type_id else None
                )

            assignments = {
                "name": payload.name,
                "description": payload.description,
                "priority": payload.priority,
                "estimated_effort_seconds": payload.estimated_effort_seconds,
                "planned_start_at": payload.planned_start_at,
                "deadline_at": payload.deadline_at,
                "target_start_date": payload.target_start_date,
                "target_end_date": payload.target_end_date,
            }
            for field, value in assignments.items():
                if field in payload.model_fields_set:
                    if field == "name":
                        assert value is not None
                    if getattr(row, field) != value:
                        setattr(row, field, value)
                        changed = True

            if "characteristic_overrides" in payload.model_fields_set and self._replace_overrides(
                row, payload.characteristic_overrides
            ):
                changed = True

            if "status" in payload.model_fields_set:
                assert payload.status is not None
                if WorkItemStatus(row.status) is not payload.status:
                    self._transition_status(row, payload.status)
                    changed = True

            self._validate_work_item_dates(
                WorkItemKind(row.kind),
                row.planned_start_at,
                row.deadline_at,
                row.target_start_date,
                row.target_end_date,
            )

            if changed:
                row.version += 1
                row.updated_at = utc_now()
                row.save()

            return _work_item_response(row, work_type)

    def delete_work_item(
        self,
        work_item_id: UUID,
        if_match: str | None,
    ) -> None:
        with transaction.atomic():
            row = self._locked_live_work_item(work_item_id)
            if row is None:
                raise self._work_item_not_found()

            require_etag(
                if_match,
                make_etag("work-item", row.id, row.version),
            )

            if WorkItem.objects.filter(
                owner_id=self.owner_id,
                parent_id=row.id,
                deleted_at__isnull=True,
            ).exists():
                raise TaskillerAPIError(
                    409,
                    "work_item_has_children",
                    "Work item has children",
                    "Move or delete the child work items before deleting this item.",
                )

            now = utc_now()
            row.deleted_at = now
            row.updated_at = now
            row.version += 1
            row.save(update_fields=["deleted_at", "updated_at", "version"])

    def list_children(self, work_item_id: UUID) -> dict[str, object]:
        parent = self._live_work_item(work_item_id)
        if parent is None:
            raise self._work_item_not_found()

        rows = list(
            WorkItem.objects.filter(
                owner_id=self.owner_id,
                parent_id=parent.id,
                deleted_at__isnull=True,
            ).order_by("position", "id")
        )
        return {"items": self._item_responses(rows)}

    def get_tree(self, work_item_id: UUID) -> dict[str, Any]:
        root = self._live_work_item(work_item_id)
        if root is None:
            raise self._work_item_not_found()

        items = [root]
        direct = list(
            WorkItem.objects.filter(
                owner_id=self.owner_id,
                parent_id=root.id,
                deleted_at__isnull=True,
            ).order_by("position", "id")
        )
        items.extend(direct)

        if root.kind == WorkItemKind.PROJECT.value:
            sprint_ids = [item.id for item in direct if item.kind == WorkItemKind.SPRINT.value]
            if sprint_ids:
                grandchildren = list(
                    WorkItem.objects.filter(
                        owner_id=self.owner_id,
                        parent_id__in=sprint_ids,
                        deleted_at__isnull=True,
                    ).order_by("parent_id", "position", "id")
                )
                items.extend(grandchildren)

        responses = {
            item.id: response
            for item, response in zip(
                items,
                self._item_responses(items),
                strict=True,
            )
        }
        children: dict[UUID, list[WorkItem]] = defaultdict(list)
        for item in items[1:]:
            if item.parent_id is not None:
                children[item.parent_id].append(item)
        for siblings in children.values():
            siblings.sort(key=lambda item: (item.position, item.id))

        def build(item: WorkItem) -> dict[str, Any]:
            return {
                **responses[item.id],
                "children": [build(child) for child in children.get(item.id, [])],
            }

        return build(root)

    def reorder_work_item(
        self,
        work_item_id: UUID,
        payload: ReorderWorkItemRequest,
        if_match: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope = f"work-items:{work_item_id}:reorder"
        request_body = _dump(payload)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            row = self._locked_live_work_item(work_item_id)
            if row is None:
                raise self._work_item_not_found()
            require_etag(
                if_match,
                make_etag("work-item", row.id, row.version),
            )

            self._lock_sibling_namespace(row.parent_id)

            if payload.before_id == row.id or payload.after_id == row.id:
                raise TaskillerAPIError(
                    409,
                    "invalid_reorder_anchor",
                    "Invalid reorder anchor",
                    "A work item cannot be positioned relative to itself.",
                )

            siblings = list(
                WorkItem.objects.select_for_update()
                .filter(
                    owner_id=self.owner_id,
                    parent_id=row.parent_id,
                    deleted_at__isnull=True,
                )
                .order_by("position", "id")
            )
            remaining = [item for item in siblings if item.id != row.id]
            anchor_id = payload.before_id or payload.after_id
            anchor_index: int | None = None

            if anchor_id is not None:
                for index, item in enumerate(remaining):
                    if item.id == anchor_id:
                        anchor_index = index
                        break
                if anchor_index is None:
                    raise TaskillerAPIError(
                        409,
                        "invalid_reorder_anchor",
                        "Invalid reorder anchor",
                        "The reorder anchor must be a live sibling of the work item.",
                    )

            if payload.before_id is not None:
                insertion_index = anchor_index or 0
            elif payload.after_id is not None:
                assert anchor_index is not None
                insertion_index = anchor_index + 1
            else:
                insertion_index = len(remaining)

            ordered = [*remaining]
            ordered.insert(insertion_index, row)
            now = utc_now()
            original_position = row.position
            positioned = self._assign_gap_position(
                row,
                ordered,
                insertion_index,
            )
            if not positioned:
                self._rebalance_positions(ordered, now)
            elif row.position != original_position:
                row.version += 1
                row.updated_at = now
                row.save(update_fields=["position", "version", "updated_at"])

            work_type = self._available_work_type(row.work_type_id) if row.work_type_id else None
            response = _work_item_response(row, work_type)
            complete_idempotency(
                owner_id=self.owner_id,
                scope=scope,
                key=idempotency_key,
                response_status=200,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_project_next_action(
        self,
        project_id: UUID,
    ) -> dict[str, Any]:
        root = self._live_work_item(project_id)
        if root is None:
            raise self._work_item_not_found()
        if root.kind != WorkItemKind.PROJECT.value:
            raise TaskillerAPIError(
                422,
                "invalid_project_target",
                "Project required",
                "The next-action endpoint can only be used with a Project work item.",
            )
        if WorkItemStatus(root.status) in _TERMINAL_STATUSES:
            return {"nextAction": None}

        tree = self.get_tree(project_id)

        def find(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
            for node in nodes:
                if WorkItemStatus(node["status"]) in _TERMINAL_STATUSES:
                    continue
                if (
                    node["kind"] == WorkItemKind.CHORE.value
                    and WorkItemStatus(node["status"]) in _ACTIONABLE_STATUSES
                ):
                    return {key: value for key, value in node.items() if key != "children"}
                if node["kind"] == WorkItemKind.SPRINT.value:
                    nested = find(node.get("children", []))
                    if nested is not None:
                        return nested
                    if WorkItemStatus(node["status"]) in _ACTIONABLE_STATUSES:
                        return {key: value for key, value in node.items() if key != "children"}
            return None

        return {"nextAction": find(tree["children"])}

    def _available_work_type(
        self,
        work_type_id: UUID | None,
    ) -> WorkType | None:
        if work_type_id is None:
            return None
        return (
            WorkType.objects.filter(id=work_type_id)
            .filter(Q(owner_id__isnull=True) | Q(owner_id=self.owner_id))
            .first()
        )

    def _validate_work_type_reference(
        self,
        work_type_id: UUID | None,
    ) -> WorkType | None:
        if work_type_id is None:
            return None
        row = (
            WorkType.objects.select_for_update()
            .filter(id=work_type_id)
            .filter(Q(owner_id__isnull=True) | Q(owner_id=self.owner_id))
            .first()
        )
        if row is None:
            raise TaskillerAPIError(
                422,
                "invalid_work_type",
                "Invalid work type",
                "workTypeId must reference a built-in or caller-owned work type.",
            )
        return row

    def _live_work_item(
        self,
        work_item_id: UUID,
    ) -> WorkItem | None:
        return WorkItem.objects.filter(
            id=work_item_id,
            owner_id=self.owner_id,
            deleted_at__isnull=True,
        ).first()

    def _locked_live_work_item(
        self,
        work_item_id: UUID,
    ) -> WorkItem | None:
        return (
            WorkItem.objects.select_for_update()
            .filter(
                id=work_item_id,
                owner_id=self.owner_id,
                deleted_at__isnull=True,
            )
            .first()
        )

    def _validate_hierarchy(
        self,
        kind: WorkItemKind,
        parent_id: UUID | None,
        work_item_id: UUID | None = None,
    ) -> WorkItem | None:
        if kind is WorkItemKind.PROJECT:
            if parent_id is not None:
                raise self._invalid_hierarchy("Projects cannot have a parent.")
            return None

        if kind is WorkItemKind.SPRINT and parent_id is None:
            raise self._invalid_hierarchy("Sprints must belong to a Project.")
        if parent_id is None:
            return None
        if work_item_id == parent_id:
            raise self._invalid_hierarchy("A work item cannot be its own parent.")

        parent = (
            WorkItem.objects.select_for_update()
            .filter(
                id=parent_id,
                owner_id=self.owner_id,
                deleted_at__isnull=True,
            )
            .first()
        )
        if parent is None:
            raise self._invalid_hierarchy("The requested parent does not exist.")
        if kind is WorkItemKind.SPRINT and parent.kind != WorkItemKind.PROJECT.value:
            raise self._invalid_hierarchy("A Sprint parent must be a Project.")
        if kind is WorkItemKind.CHORE and parent.kind not in {
            WorkItemKind.PROJECT.value,
            WorkItemKind.SPRINT.value,
        }:
            raise self._invalid_hierarchy("A Chore parent must be a Project or Sprint.")
        return parent

    def _lock_sibling_namespace(
        self,
        parent_id: UUID | None,
    ) -> None:
        if parent_id is None:
            TaskillerUser.objects.select_for_update().get(id=self.owner_id)
            return
        WorkItem.objects.select_for_update().get(
            id=parent_id,
            owner_id=self.owner_id,
            deleted_at__isnull=True,
        )

    def _next_position(
        self,
        parent_id: UUID | None,
        *,
        exclude_id: UUID | None = None,
    ) -> int:
        self._lock_sibling_namespace(parent_id)
        query = WorkItem.objects.filter(
            owner_id=self.owner_id,
            parent_id=parent_id,
            deleted_at__isnull=True,
        )
        if exclude_id is not None:
            query = query.exclude(id=exclude_id)
        maximum = query.aggregate(maximum=Max("position"))["maximum"]
        return int(maximum or 0) + _POSITION_STEP

    def _item_responses(
        self,
        items: list[WorkItem],
    ) -> list[dict[str, Any]]:
        work_type_ids = {item.work_type_id for item in items if item.work_type_id is not None}
        work_types = {row.id: row for row in WorkType.objects.filter(id__in=work_type_ids)}
        return [
            _work_item_response(
                item,
                work_types.get(item.work_type_id),
            )
            for item in items
        ]

    @staticmethod
    def _replace_overrides(
        row: WorkItem,
        overrides: PartialWorkCharacteristics | None,
    ) -> bool:
        values = overrides.supplied_values() if overrides is not None else {}
        changed = False
        for field in _CHARACTERISTIC_FIELDS:
            attribute = f"{field}_override"
            value = values.get(field)
            if getattr(row, attribute) != value:
                setattr(row, attribute, value)
                changed = True
        return changed

    @staticmethod
    def _validate_work_item_dates(
        kind: WorkItemKind,
        planned_start_at: datetime | None,
        deadline_at: datetime | None,
        target_start_date: date | None,
        target_end_date: date | None,
    ) -> None:
        if (
            planned_start_at is not None
            and deadline_at is not None
            and planned_start_at > deadline_at
        ):
            raise TaskillerAPIError(
                422,
                "invalid_date_range",
                "Invalid date range",
                "plannedStartAt cannot be after deadlineAt.",
            )
        if (
            target_start_date is not None
            and target_end_date is not None
            and target_start_date > target_end_date
        ):
            raise TaskillerAPIError(
                422,
                "invalid_date_range",
                "Invalid date range",
                "targetStartDate cannot be after targetEndDate.",
            )
        if kind is not WorkItemKind.PROJECT and (
            target_start_date is not None or target_end_date is not None
        ):
            raise TaskillerAPIError(
                422,
                "invalid_date_range",
                "Project dates require a Project",
                "targetStartDate and targetEndDate are only valid for Projects.",
            )

    @staticmethod
    def _initial_terminal_timestamps(
        status: WorkItemStatus,
        now: datetime,
    ) -> tuple[datetime | None, datetime | None, datetime | None]:
        return (
            now if status is WorkItemStatus.COMPLETED else None,
            now if status is WorkItemStatus.CANCELLED else None,
            now if status is WorkItemStatus.ARCHIVED else None,
        )

    @staticmethod
    def _transition_status(
        row: WorkItem,
        target: WorkItemStatus,
    ) -> None:
        current = WorkItemStatus(row.status)
        if target is current:
            return
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise TaskillerAPIError(
                409,
                "work_item_state_conflict",
                "Invalid work item state transition",
                f"A work item cannot transition from {current.value} to {target.value}.",
            )

        now = utc_now()
        row.status = target.value
        if target is WorkItemStatus.COMPLETED:
            row.completed_at = now
            row.cancelled_at = None
            row.archived_at = None
        elif target is WorkItemStatus.CANCELLED:
            row.cancelled_at = now
            row.completed_at = None
            row.archived_at = None
        elif target is WorkItemStatus.ARCHIVED:
            row.archived_at = now
        elif target is WorkItemStatus.READY:
            row.completed_at = None
            row.cancelled_at = None
            row.archived_at = None

    @staticmethod
    def _assign_gap_position(
        row: WorkItem,
        ordered: list[WorkItem],
        index: int,
    ) -> bool:
        previous = ordered[index - 1] if index > 0 else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if previous is None and following is None:
            row.position = _POSITION_STEP
        elif previous is None and following is not None:
            if following.position <= 1:
                return False
            row.position = following.position // 2
        elif following is None and previous is not None:
            row.position = previous.position + _POSITION_STEP
        else:
            assert previous is not None and following is not None
            gap = following.position - previous.position
            if gap <= 1:
                return False
            row.position = previous.position + gap // 2
            if row.position in {previous.position, following.position}:
                return False

        return True

    @staticmethod
    def _rebalance_positions(
        ordered: list[WorkItem],
        now: datetime,
    ) -> None:
        for index, item in enumerate(ordered, start=1):
            position = index * _POSITION_STEP
            if item.position == position:
                continue
            item.position = position
            item.updated_at = now
            item.version += 1
            item.save(update_fields=["position", "updated_at", "version"])

    @staticmethod
    def _encode_cursor(
        created_at: datetime,
        item_id: UUID,
    ) -> str:
        payload = json.dumps(
            {
                "createdAt": created_at.isoformat(),
                "id": str(item_id),
            },
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode())
            created_at = datetime.fromisoformat(str(payload["createdAt"]))
            if created_at.tzinfo is None:
                raise ValueError("cursor timestamp must include a timezone")
            return created_at, UUID(str(payload["id"]))
        except (
            binascii.Error,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise TaskillerAPIError(
                422,
                "invalid_cursor",
                "Invalid cursor",
                "The pagination cursor is malformed or no longer supported.",
            ) from exc

    @staticmethod
    def _work_item_not_found() -> TaskillerAPIError:
        return TaskillerAPIError(
            404,
            "work_item_not_found",
            "Work item not found",
        )

    @staticmethod
    def _work_type_not_found() -> TaskillerAPIError:
        return TaskillerAPIError(
            404,
            "work_type_not_found",
            "Work type not found",
        )

    @staticmethod
    def _system_work_type_immutable() -> TaskillerAPIError:
        return TaskillerAPIError(
            403,
            "system_work_type_immutable",
            "System work type is immutable",
            "Built-in work types cannot be edited or deleted.",
        )

    @staticmethod
    def _slug_conflict() -> TaskillerAPIError:
        return TaskillerAPIError(
            409,
            "work_type_slug_conflict",
            "Work type slug already exists",
            "Choose a different slug for this custom work type.",
        )

    @staticmethod
    def _invalid_hierarchy(detail: str) -> TaskillerAPIError:
        return TaskillerAPIError(
            409,
            "invalid_work_hierarchy",
            "Invalid work hierarchy",
            detail,
        )
