from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.core.idempotency import claim_idempotency, complete_idempotency
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import User
from taskiller.users.etag import make_etag, require_etag
from taskiller.work.models import WorkItem, WorkType
from taskiller.work.presenters import work_item_to_response, work_type_to_response
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    CreateWorkTypeRequest,
    PageMeta,
    PartialWorkCharacteristics,
    ProjectNextActionResponse,
    ReorderWorkItemRequest,
    UpdateWorkItemRequest,
    UpdateWorkTypeRequest,
    WorkItemChildrenResponse,
    WorkItemKind,
    WorkItemPage,
    WorkItemResponse,
    WorkItemStatus,
    WorkItemTreeNode,
    WorkTypeListResponse,
    WorkTypeResponse,
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
    WorkItemStatus.IN_PROGRESS: {WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED},
    WorkItemStatus.COMPLETED: {WorkItemStatus.READY, WorkItemStatus.ARCHIVED},
    WorkItemStatus.CANCELLED: {WorkItemStatus.READY, WorkItemStatus.ARCHIVED},
    WorkItemStatus.ARCHIVED: {WorkItemStatus.READY},
}


class WorkService:
    def __init__(self, db: AsyncSession, owner_id: UUID, idempotency_ttl_hours: int) -> None:
        self.db = db
        self.owner_id = owner_id
        self.idempotency_ttl_hours = idempotency_ttl_hours

    async def list_work_types(self) -> WorkTypeListResponse:
        rows = list(
            (
                await self.db.scalars(
                    select(WorkType)
                    .where(or_(WorkType.owner_id.is_(None), WorkType.owner_id == self.owner_id))
                    .order_by(WorkType.is_system.desc(), WorkType.display_name, WorkType.id)
                )
            ).all()
        )
        return WorkTypeListResponse(items=[work_type_to_response(row) for row in rows])

    async def create_work_type(
        self,
        payload: CreateWorkTypeRequest,
        idempotency_key: str,
    ) -> WorkTypeResponse:
        scope = "work-types:create"
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return WorkTypeResponse.model_validate(replay.response_body)

        existing = await self.db.scalar(
            select(WorkType.id).where(
                WorkType.owner_id == self.owner_id,
                func.lower(WorkType.slug) == payload.slug.casefold(),
            )
        )
        if existing is not None:
            await self.db.rollback()
            raise ApiError(
                409,
                "work_type_slug_conflict",
                "Work type slug already exists",
                "Choose a different slug for this custom work type.",
            )

        now = utc_now()
        row = WorkType(
            id=uuid4(),
            owner_id=self.owner_id,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            cognitive_demand=payload.characteristics.cognitive_demand.value,
            interruption_sensitivity=payload.characteristics.interruption_sensitivity.value,
            continuity_need=payload.characteristics.continuity_need.value,
            repetitiveness=payload.characteristics.repetitiveness.value,
            physicality=payload.characteristics.physicality.value,
            learning_mode=payload.characteristics.learning_mode.value,
            is_system=False,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ApiError(
                409,
                "work_type_slug_conflict",
                "Work type slug already exists",
                "Choose a different slug for this custom work type.",
            ) from exc

        response = work_type_to_response(row)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_work_type(self, work_type_id: UUID) -> WorkTypeResponse:
        row = await self._available_work_type(work_type_id)
        if row is None:
            raise self._work_type_not_found()
        return work_type_to_response(row)

    async def update_work_type(
        self,
        work_type_id: UUID,
        payload: UpdateWorkTypeRequest,
        if_match: str | None,
    ) -> WorkTypeResponse:
        row = (
            await self.db.execute(
                select(WorkType)
                .where(
                    WorkType.id == work_type_id,
                    or_(WorkType.owner_id.is_(None), WorkType.owner_id == self.owner_id),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            await self.db.rollback()
            raise self._work_type_not_found()
        if row.is_system:
            await self.db.rollback()
            raise self._system_work_type_immutable()
        require_etag(if_match, make_etag("work-type", row.id, row.version))

        if "display_name" in payload.model_fields_set:
            row.display_name = payload.display_name or row.display_name
        if "description" in payload.model_fields_set:
            row.description = payload.description
        if "characteristics" in payload.model_fields_set and payload.characteristics is not None:
            row.cognitive_demand = payload.characteristics.cognitive_demand.value
            row.interruption_sensitivity = payload.characteristics.interruption_sensitivity.value
            row.continuity_need = payload.characteristics.continuity_need.value
            row.repetitiveness = payload.characteristics.repetitiveness.value
            row.physicality = payload.characteristics.physicality.value
            row.learning_mode = payload.characteristics.learning_mode.value

        if self.db.is_modified(row, include_collections=False):
            row.version += 1
            row.updated_at = utc_now()
            await self.db.commit()
        else:
            await self.db.commit()
        return work_type_to_response(row)

    async def delete_work_type(self, work_type_id: UUID, if_match: str | None) -> None:
        row = (
            await self.db.execute(
                select(WorkType)
                .where(
                    WorkType.id == work_type_id,
                    or_(WorkType.owner_id.is_(None), WorkType.owner_id == self.owner_id),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            await self.db.rollback()
            raise self._work_type_not_found()
        if row.is_system:
            await self.db.rollback()
            raise self._system_work_type_immutable()
        require_etag(if_match, make_etag("work-type", row.id, row.version))
        await self.db.delete(row)
        await self.db.commit()

    async def list_work_items(
        self,
        *,
        limit: int,
        cursor: str | None,
        kind: WorkItemKind | None,
        status: WorkItemStatus | None,
        parent_id: UUID | None,
        include_deleted: bool,
    ) -> WorkItemPage:
        stmt = select(WorkItem).where(WorkItem.owner_id == self.owner_id)
        if not include_deleted:
            stmt = stmt.where(WorkItem.deleted_at.is_(None))
        if kind is not None:
            stmt = stmt.where(WorkItem.kind == kind.value)
        if status is not None:
            stmt = stmt.where(WorkItem.status == status.value)
        if parent_id is not None:
            stmt = stmt.where(WorkItem.parent_id == parent_id)
        if cursor is not None:
            cursor_time, cursor_id = self._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    WorkItem.created_at < cursor_time,
                    and_(WorkItem.created_at == cursor_time, WorkItem.id < cursor_id),
                )
            )
        rows = list(
            (
                await self.db.scalars(
                    stmt.order_by(WorkItem.created_at.desc(), WorkItem.id.desc()).limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        responses = await self._item_responses(page_rows)
        next_cursor = None
        if has_more and page_rows:
            tail = page_rows[-1]
            next_cursor = self._encode_cursor(tail.created_at, tail.id)
        return WorkItemPage(
            items=responses,
            page=PageMeta(has_more=has_more, next_cursor=next_cursor),
        )

    async def create_work_item(
        self,
        payload: CreateWorkItemRequest,
        idempotency_key: str,
    ) -> WorkItemResponse:
        scope = "work-items:create"
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return WorkItemResponse.model_validate(replay.response_body)

        await self._validate_hierarchy(payload.kind, payload.parent_id)
        work_type = await self._validate_work_type_reference(payload.work_type_id)
        self._validate_work_item_dates(
            payload.kind,
            payload.planned_start_at,
            payload.deadline_at,
            payload.target_start_date,
            payload.target_end_date,
        )
        now = utc_now()
        position = await self._next_position(payload.parent_id)
        completed_at, cancelled_at, archived_at = self._initial_terminal_timestamps(
            payload.status, now
        )
        row = WorkItem(
            id=uuid4(),
            owner_id=self.owner_id,
            kind=payload.kind.value,
            parent_id=payload.parent_id,
            work_type_id=work_type.id if work_type is not None else None,
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
        self.db.add(row)
        await self.db.flush()
        response = work_item_to_response(row, work_type)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_work_item(self, work_item_id: UUID) -> WorkItemResponse:
        row = await self._live_work_item(work_item_id)
        if row is None:
            raise self._work_item_not_found()
        work_type = await self._available_work_type(row.work_type_id) if row.work_type_id else None
        return work_item_to_response(row, work_type)

    async def update_work_item(
        self,
        work_item_id: UUID,
        payload: UpdateWorkItemRequest,
        if_match: str | None,
    ) -> WorkItemResponse:
        row = await self._locked_live_work_item(work_item_id)
        if row is None:
            await self.db.rollback()
            raise self._work_item_not_found()
        require_etag(if_match, make_etag("work-item", row.id, row.version))

        if "parent_id" in payload.model_fields_set and payload.parent_id != row.parent_id:
            await self._validate_hierarchy(WorkItemKind(row.kind), payload.parent_id, row.id)
            row.parent_id = payload.parent_id
            row.position = await self._next_position(payload.parent_id, exclude_id=row.id)

        work_type: WorkType | None
        if "work_type_id" in payload.model_fields_set:
            work_type = await self._validate_work_type_reference(payload.work_type_id)
            row.work_type_id = work_type.id if work_type is not None else None
        else:
            work_type = (
                await self._available_work_type(row.work_type_id) if row.work_type_id else None
            )

        if "name" in payload.model_fields_set and payload.name is not None:
            row.name = payload.name
        if "description" in payload.model_fields_set:
            row.description = payload.description
        if "priority" in payload.model_fields_set:
            row.priority = payload.priority
        if "estimated_effort_seconds" in payload.model_fields_set:
            row.estimated_effort_seconds = payload.estimated_effort_seconds
        if "planned_start_at" in payload.model_fields_set:
            row.planned_start_at = payload.planned_start_at
        if "deadline_at" in payload.model_fields_set:
            row.deadline_at = payload.deadline_at
        if "target_start_date" in payload.model_fields_set:
            row.target_start_date = payload.target_start_date
        if "target_end_date" in payload.model_fields_set:
            row.target_end_date = payload.target_end_date
        if "characteristic_overrides" in payload.model_fields_set:
            self._replace_overrides(row, payload.characteristic_overrides)
        if "status" in payload.model_fields_set and payload.status is not None:
            self._transition_status(row, payload.status)

        self._validate_work_item_dates(
            WorkItemKind(row.kind),
            row.planned_start_at,
            row.deadline_at,
            row.target_start_date,
            row.target_end_date,
        )

        if self.db.is_modified(row, include_collections=False):
            row.version += 1
            row.updated_at = utc_now()
            await self.db.commit()
        else:
            await self.db.commit()
        return work_item_to_response(row, work_type)

    async def delete_work_item(self, work_item_id: UUID, if_match: str | None) -> None:
        row = await self._locked_live_work_item(work_item_id)
        if row is None:
            await self.db.rollback()
            raise self._work_item_not_found()
        require_etag(if_match, make_etag("work-item", row.id, row.version))
        child_id = await self.db.scalar(
            select(WorkItem.id)
            .where(
                WorkItem.owner_id == self.owner_id,
                WorkItem.parent_id == row.id,
                WorkItem.deleted_at.is_(None),
            )
            .limit(1)
        )
        if child_id is not None:
            await self.db.rollback()
            raise ApiError(
                409,
                "work_item_has_children",
                "Work item has children",
                "Move or delete the child work items before deleting this item.",
            )
        now = utc_now()
        row.deleted_at = now
        row.updated_at = now
        row.version += 1
        await self.db.commit()

    async def list_children(self, work_item_id: UUID) -> WorkItemChildrenResponse:
        parent = await self._live_work_item(work_item_id)
        if parent is None:
            raise self._work_item_not_found()
        rows = list(
            (
                await self.db.scalars(
                    select(WorkItem)
                    .where(
                        WorkItem.owner_id == self.owner_id,
                        WorkItem.parent_id == parent.id,
                        WorkItem.deleted_at.is_(None),
                    )
                    .order_by(WorkItem.position, WorkItem.id)
                )
            ).all()
        )
        return WorkItemChildrenResponse(items=await self._item_responses(rows))

    async def get_tree(self, work_item_id: UUID) -> WorkItemTreeNode:
        root = await self._live_work_item(work_item_id)
        if root is None:
            raise self._work_item_not_found()
        items = [root]
        direct = list(
            (
                await self.db.scalars(
                    select(WorkItem)
                    .where(
                        WorkItem.owner_id == self.owner_id,
                        WorkItem.parent_id == root.id,
                        WorkItem.deleted_at.is_(None),
                    )
                    .order_by(WorkItem.position, WorkItem.id)
                )
            ).all()
        )
        items.extend(direct)
        if root.kind == WorkItemKind.PROJECT.value:
            sprint_ids = [item.id for item in direct if item.kind == WorkItemKind.SPRINT.value]
            if sprint_ids:
                grandchildren = list(
                    (
                        await self.db.scalars(
                            select(WorkItem)
                            .where(
                                WorkItem.owner_id == self.owner_id,
                                WorkItem.parent_id.in_(sprint_ids),
                                WorkItem.deleted_at.is_(None),
                            )
                            .order_by(WorkItem.parent_id, WorkItem.position, WorkItem.id)
                        )
                    ).all()
                )
                items.extend(grandchildren)
        item_responses = await self._item_responses(items)
        responses = {
            item.id: response
            for item, response in zip(items, item_responses, strict=True)
        }
        children: dict[UUID, list[WorkItem]] = defaultdict(list)
        for item in items[1:]:
            if item.parent_id is not None:
                children[item.parent_id].append(item)
        for siblings in children.values():
            siblings.sort(key=lambda item: (item.position, item.id))

        def build(item: WorkItem) -> WorkItemTreeNode:
            response = responses[item.id]
            return WorkItemTreeNode(
                **response.model_dump(),
                children=[build(child) for child in children.get(item.id, [])],
            )

        return build(root)

    async def reorder_work_item(
        self,
        work_item_id: UUID,
        payload: ReorderWorkItemRequest,
        if_match: str | None,
        idempotency_key: str,
    ) -> WorkItemResponse:
        scope = f"work-items:{work_item_id}:reorder"
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            request_payload=payload.model_dump(mode="json", by_alias=True),
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return WorkItemResponse.model_validate(replay.response_body)

        row = await self._locked_live_work_item(work_item_id)
        if row is None:
            await self.db.rollback()
            raise self._work_item_not_found()
        require_etag(if_match, make_etag("work-item", row.id, row.version))
        await self._lock_sibling_namespace(row.parent_id)
        if payload.before_id == row.id or payload.after_id == row.id:
            await self.db.rollback()
            raise ApiError(
                409,
                "invalid_reorder_anchor",
                "Invalid reorder anchor",
                "A work item cannot be positioned relative to itself.",
            )

        siblings = list(
            (
                await self.db.scalars(
                    select(WorkItem)
                    .where(
                        WorkItem.owner_id == self.owner_id,
                        WorkItem.parent_id == row.parent_id,
                        WorkItem.deleted_at.is_(None),
                    )
                    .order_by(WorkItem.position, WorkItem.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        remaining = [item for item in siblings if item.id != row.id]
        anchor_id = payload.before_id or payload.after_id
        anchor_index = None
        if anchor_id is not None:
            for index, item in enumerate(remaining):
                if item.id == anchor_id:
                    anchor_index = index
                    break
            if anchor_index is None:
                await self.db.rollback()
                raise ApiError(
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
        if not self._assign_gap_position(row, ordered, insertion_index, now):
            self._rebalance_positions(ordered, now)
        elif self.db.is_modified(row, include_collections=False):
            row.version += 1
            row.updated_at = now

        work_type = await self._available_work_type(row.work_type_id) if row.work_type_id else None
        response = work_item_to_response(row, work_type)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope=scope,
            key=idempotency_key,
            response_status=200,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_project_next_action(self, project_id: UUID) -> ProjectNextActionResponse:
        root = await self._live_work_item(project_id)
        if root is None:
            raise self._work_item_not_found()
        if root.kind != WorkItemKind.PROJECT.value:
            raise ApiError(
                422,
                "invalid_project_target",
                "Project required",
                "The next-action endpoint can only be used with a Project work item.",
            )
        if WorkItemStatus(root.status) in _TERMINAL_STATUSES:
            return ProjectNextActionResponse(next_action=None)
        tree = await self.get_tree(project_id)

        def find(nodes: list[WorkItemTreeNode]) -> WorkItemResponse | None:
            for node in nodes:
                if node.status in _TERMINAL_STATUSES:
                    continue
                if node.kind is WorkItemKind.CHORE and node.status in _ACTIONABLE_STATUSES:
                    return WorkItemResponse.model_validate(node.model_dump(exclude={"children"}))
                if node.kind is WorkItemKind.SPRINT:
                    nested = find(node.children)
                    if nested is not None:
                        return nested
                    if node.status in _ACTIONABLE_STATUSES:
                        return WorkItemResponse.model_validate(
                            node.model_dump(exclude={"children"})
                        )
            return None

        return ProjectNextActionResponse(next_action=find(tree.children))

    async def _available_work_type(self, work_type_id: UUID) -> WorkType | None:
        return (
            await self.db.execute(
                select(WorkType).where(
                    WorkType.id == work_type_id,
                    or_(WorkType.owner_id.is_(None), WorkType.owner_id == self.owner_id),
                )
            )
        ).scalar_one_or_none()

    async def _validate_work_type_reference(self, work_type_id: UUID | None) -> WorkType | None:
        if work_type_id is None:
            return None
        row = (
            await self.db.execute(
                select(WorkType)
                .where(
                    WorkType.id == work_type_id,
                    or_(WorkType.owner_id.is_(None), WorkType.owner_id == self.owner_id),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApiError(
                422,
                "invalid_work_type",
                "Invalid work type",
                "workTypeId must reference a built-in or caller-owned work type.",
            )
        return row

    async def _live_work_item(self, work_item_id: UUID) -> WorkItem | None:
        return (
            await self.db.execute(
                select(WorkItem).where(
                    WorkItem.id == work_item_id,
                    WorkItem.owner_id == self.owner_id,
                    WorkItem.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def _locked_live_work_item(self, work_item_id: UUID) -> WorkItem | None:
        return (
            await self.db.execute(
                select(WorkItem)
                .where(
                    WorkItem.id == work_item_id,
                    WorkItem.owner_id == self.owner_id,
                    WorkItem.deleted_at.is_(None),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _validate_hierarchy(
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
            await self.db.execute(
                select(WorkItem)
                .where(
                    WorkItem.id == parent_id,
                    WorkItem.owner_id == self.owner_id,
                    WorkItem.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
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

    async def _next_position(
        self,
        parent_id: UUID | None,
        *,
        exclude_id: UUID | None = None,
    ) -> int:
        await self._lock_sibling_namespace(parent_id)
        parent_filter = (
            WorkItem.parent_id.is_(None)
            if parent_id is None
            else WorkItem.parent_id == parent_id
        )
        stmt = select(func.max(WorkItem.position)).where(
            WorkItem.owner_id == self.owner_id,
            WorkItem.deleted_at.is_(None),
            parent_filter,
        )
        if exclude_id is not None:
            stmt = stmt.where(WorkItem.id != exclude_id)
        maximum = await self.db.scalar(stmt)
        return int(maximum or 0) + _POSITION_STEP

    async def _lock_sibling_namespace(self, parent_id: UUID | None) -> None:
        if parent_id is None:
            await self.db.execute(
                select(User.id).where(User.id == self.owner_id).with_for_update()
            )
            return
        await self.db.execute(
            select(WorkItem.id)
            .where(
                WorkItem.id == parent_id,
                WorkItem.owner_id == self.owner_id,
                WorkItem.deleted_at.is_(None),
            )
            .with_for_update()
        )

    async def _item_responses(self, items: list[WorkItem]) -> list[WorkItemResponse]:
        work_type_ids = {item.work_type_id for item in items if item.work_type_id is not None}
        work_types: dict[UUID, WorkType] = {}
        if work_type_ids:
            rows = list(
                (
                    await self.db.scalars(
                        select(WorkType).where(WorkType.id.in_(work_type_ids))
                    )
                ).all()
            )
            work_types = {row.id: row for row in rows}
        return [
            work_item_to_response(
                item,
                work_types.get(item.work_type_id) if item.work_type_id is not None else None,
            )
            for item in items
        ]

    @staticmethod
    def _replace_overrides(
        row: WorkItem,
        overrides: PartialWorkCharacteristics | None,
    ) -> None:
        values = overrides.supplied_values() if overrides is not None else {}
        for field in _CHARACTERISTIC_FIELDS:
            setattr(row, f"{field}_override", values.get(field))

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
            raise ApiError(
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
            raise ApiError(
                422,
                "invalid_date_range",
                "Invalid date range",
                "targetStartDate cannot be after targetEndDate.",
            )
        if kind is not WorkItemKind.PROJECT and (
            target_start_date is not None or target_end_date is not None
        ):
            raise ApiError(
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
    def _transition_status(row: WorkItem, target: WorkItemStatus) -> None:
        current = WorkItemStatus(row.status)
        if target is current:
            return
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise ApiError(
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
        now: datetime,
    ) -> bool:
        previous = ordered[index - 1] if index > 0 else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if previous is None and following is None:
            row.position = _POSITION_STEP
            return True
        if previous is None and following is not None:
            if following.position <= 1:
                return False
            row.position = following.position // 2
            return row.position < following.position
        if following is None and previous is not None:
            row.position = previous.position + _POSITION_STEP
            return True
        assert previous is not None and following is not None
        gap = following.position - previous.position
        if gap <= 1:
            return False
        row.position = previous.position + gap // 2
        if row.position in {previous.position, following.position}:
            return False
        row.updated_at = now
        return True

    def _rebalance_positions(self, ordered: list[WorkItem], now: datetime) -> None:
        for index, item in enumerate(ordered, start=1):
            position = index * _POSITION_STEP
            if item.position == position:
                continue
            item.position = position
            item.updated_at = now
            item.version += 1

    @staticmethod
    def _encode_cursor(created_at: datetime, item_id: UUID) -> str:
        payload = json.dumps(
            {"createdAt": created_at.isoformat(), "id": str(item_id)},
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
        except (binascii.Error, KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                422,
                "invalid_cursor",
                "Invalid cursor",
                "The pagination cursor is malformed or no longer supported.",
            ) from exc

    @staticmethod
    def _work_item_not_found() -> ApiError:
        return ApiError(404, "work_item_not_found", "Work item not found")

    @staticmethod
    def _work_type_not_found() -> ApiError:
        return ApiError(404, "work_type_not_found", "Work type not found")

    @staticmethod
    def _system_work_type_immutable() -> ApiError:
        return ApiError(
            403,
            "system_work_type_immutable",
            "System work type is immutable",
            "Built-in work types cannot be edited or deleted.",
        )

    @staticmethod
    def _invalid_hierarchy(detail: str) -> ApiError:
        return ApiError(409, "invalid_work_hierarchy", "Invalid work hierarchy", detail)
