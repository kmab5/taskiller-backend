from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from taskiller.analytics.service import AnalyticsService
from taskiller.core.idempotency import claim_idempotency, complete_idempotency
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import UserPreferences
from taskiller.focus.engine import (
    ENGINE_VERSION,
    EnginePreferences,
    SprintChild,
    generate_chore_recommendation,
    generate_sprint_recommendation,
)
from taskiller.focus.models import (
    FocusPlanModel,
    FocusPlanRecommendationModel,
    FocusPlanSegmentModel,
)
from taskiller.focus.presenters import focus_plan_to_response, recommendation_to_response
from taskiller.focus.schemas import (
    CreateFocusPlanRequest,
    CreateRecommendationRequest,
    FocusPlan,
    FocusPlanPage,
    FocusPlanRecommendation,
    FocusPlanSegmentInput,
    FocusPlanSource,
    PageMeta,
    RecommendationProvenance,
    RecommendationReasonLabel,
    RecommendationStrategy,
    UpdateFocusPlanRequest,
)
from taskiller.users.etag import make_etag, require_etag
from taskiller.work.models import WorkItem, WorkType
from taskiller.work.presenters import effective_characteristics
from taskiller.work.schemas import WorkCharacteristics, WorkItemKind, WorkItemStatus

_TERMINAL = {
    WorkItemStatus.COMPLETED.value,
    WorkItemStatus.CANCELLED.value,
    WorkItemStatus.ARCHIVED.value,
}


class FocusService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        owner_id: UUID,
        idempotency_ttl_hours: int,
    ) -> None:
        self.db = db
        self.owner_id = owner_id
        self.idempotency_ttl_hours = idempotency_ttl_hours

    async def create_recommendation(
        self,
        payload: CreateRecommendationRequest,
        idempotency_key: str,
    ) -> FocusPlanRecommendation:
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="focus-plan-recommendations:create",
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return FocusPlanRecommendation.model_validate(replay.response_body)

        work_item = await self._live_work_item(payload.work_item_id, lock=True)
        if work_item is None:
            raise self._not_found("work_item_not_found", "Work item not found")
        if work_item.status in _TERMINAL:
            raise ApiError(
                409,
                "work_item_not_executable",
                "Work item is not executable",
                "Completed, cancelled, or archived work cannot receive a new recommendation.",
            )
        if WorkItemKind(work_item.kind) is WorkItemKind.PROJECT:
            raise ApiError(
                422,
                "project_requires_next_action",
                "Project cannot be focused directly",
                "Resolve the Project next action and request a Focus Plan for its Sprint or Chore.",
            )

        preferences = await self._preferences()
        engine_preferences = EnginePreferences(
            strategy=RecommendationStrategy(preferences.preferred_strategy),
            work_block_min_seconds=preferences.preferred_work_block_min_seconds,
            work_block_max_seconds=preferences.preferred_work_block_max_seconds,
        )
        preference_informed = (
            payload.preferred_strategy is not RecommendationStrategy.AUTO
            or engine_preferences.strategy is not RecommendationStrategy.AUTO
            or engine_preferences.work_block_min_seconds is not None
            or engine_preferences.work_block_max_seconds is not None
        )
        personalization_signal = None
        if WorkItemKind(work_item.kind) is WorkItemKind.CHORE:
            characteristics = await self._characteristics_for(work_item)
            if characteristics is None:
                raise self._missing_context(
                    "The Chore needs a Work Type or complete characteristic overrides."
                )
            if work_item.work_type_id is not None:
                work_type = await self.db.get(WorkType, work_item.work_type_id)
                if work_type is not None:
                    personalization_signal = await AnalyticsService(
                        self.db, owner_id=self.owner_id
                    ).personalization_signal(
                        work_type_id=work_type.id,
                        work_type_slug=work_type.slug,
                    )
                    if personalization_signal is not None:
                        engine_preferences = EnginePreferences(
                            strategy=engine_preferences.strategy,
                            work_block_min_seconds=engine_preferences.work_block_min_seconds,
                            work_block_max_seconds=engine_preferences.work_block_max_seconds,
                            personal_work_block_seconds=(personalization_signal.target_seconds),
                            personal_sample_size=personalization_signal.sample_size,
                        )
            effort = work_item.estimated_effort_seconds
            if not effort:
                effort = payload.available_time_seconds
            if not effort:
                raise self._missing_context(
                    "The Chore needs estimatedEffortSeconds or availableTimeSeconds."
                )
            generated = generate_chore_recommendation(
                work_item_id=work_item.id,
                effort_seconds=effort,
                characteristics=characteristics,
                requested_strategy=payload.preferred_strategy,
                preferences=engine_preferences,
                available_time_seconds=payload.available_time_seconds,
            )
            context_snapshot: dict[str, object] = {
                "workItem": {
                    "id": str(work_item.id),
                    "kind": work_item.kind,
                    "estimatedEffortSeconds": work_item.estimated_effort_seconds,
                    "effectiveCharacteristics": characteristics.model_dump(
                        mode="json", by_alias=True
                    ),
                }
            }
        else:
            children = await self._sprint_children(work_item.id)
            if not children:
                raise self._missing_context(
                    "The Sprint needs at least one non-terminal Chore with an effort estimate."
                )
            generated = generate_sprint_recommendation(
                sprint_id=work_item.id,
                children=children,
                requested_strategy=payload.preferred_strategy,
                preferences=engine_preferences,
                available_time_seconds=payload.available_time_seconds,
            )
            context_snapshot = {
                "workItem": {
                    "id": str(work_item.id),
                    "kind": work_item.kind,
                    "children": [
                        {
                            "id": str(child.id),
                            "name": child.name,
                            "estimatedEffortSeconds": child.estimate_seconds,
                            "effectiveCharacteristics": child.characteristics.model_dump(
                                mode="json", by_alias=True
                            ),
                        }
                        for child in children
                    ],
                }
            }

        history_informed = any(
            reason.label is RecommendationReasonLabel.PERSONAL_PATTERN
            for reason in generated.reasons
        )
        provenance = (
            RecommendationProvenance.HISTORY_INFORMED
            if history_informed
            else (
                RecommendationProvenance.PREFERENCE_INFORMED
                if preference_informed
                else RecommendationProvenance.BOOTSTRAP
            )
        )
        now = utc_now()
        row = FocusPlanRecommendationModel(
            owner_id=self.owner_id,
            work_item_id=work_item.id,
            engine_version=ENGINE_VERSION,
            provenance=provenance.value,
            strategy=generated.strategy,
            input_snapshot_json={
                **context_snapshot,
                "availableTimeSeconds": payload.available_time_seconds,
                "requestedStrategy": payload.preferred_strategy.value,
                "preferences": {
                    "preferredStrategy": engine_preferences.strategy.value,
                    "preferredWorkBlockMinSeconds": engine_preferences.work_block_min_seconds,
                    "preferredWorkBlockMaxSeconds": engine_preferences.work_block_max_seconds,
                },
                "personalizationSignal": (
                    {
                        "workTypeSlug": personalization_signal.work_type_slug,
                        "sampleSize": personalization_signal.sample_size,
                        "medianFocusScore": personalization_signal.median_focus_score,
                        "targetWorkBlockSeconds": personalization_signal.target_seconds,
                    }
                    if personalization_signal is not None
                    else None
                ),
            },
            plan_snapshot_json=generated.plan.model_dump(mode="json", by_alias=True),
            reasons_json=[
                reason.model_dump(mode="json", by_alias=True) for reason in generated.reasons
            ],
            created_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        response = recommendation_to_response(row)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="focus-plan-recommendations:create",
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_recommendation(self, recommendation_id: UUID) -> FocusPlanRecommendation:
        row = await self.db.scalar(
            select(FocusPlanRecommendationModel).where(
                FocusPlanRecommendationModel.id == recommendation_id,
                FocusPlanRecommendationModel.owner_id == self.owner_id,
            )
        )
        if row is None:
            raise self._not_found("recommendation_not_found", "Recommendation not found")
        return recommendation_to_response(row)

    async def create_focus_plan(
        self,
        payload: CreateFocusPlanRequest,
        idempotency_key: str,
    ) -> FocusPlan:
        request_body = payload.model_dump(mode="json", by_alias=True)
        replay = await claim_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="focus-plans:create",
            key=idempotency_key,
            request_payload=request_body,
            ttl_hours=self.idempotency_ttl_hours,
        )
        if replay is not None:
            return FocusPlan.model_validate(replay.response_body)

        work_item_id = payload.work_item_id
        recommendation: FocusPlanRecommendationModel | None = None
        if payload.recommendation_id is not None:
            recommendation = await self.db.scalar(
                select(FocusPlanRecommendationModel).where(
                    FocusPlanRecommendationModel.id == payload.recommendation_id,
                    FocusPlanRecommendationModel.owner_id == self.owner_id,
                )
            )
            if recommendation is None:
                raise self._not_found("recommendation_not_found", "Recommendation not found")
            if work_item_id is None:
                work_item_id = recommendation.work_item_id
            elif work_item_id != recommendation.work_item_id:
                raise ApiError(
                    422,
                    "recommendation_work_item_mismatch",
                    "Recommendation does not match work item",
                    "recommendationId and workItemId must refer to the same work item.",
                )
        target = await self._validate_plan_target(work_item_id)
        await self._validate_segments(payload.segments, target)
        now = utc_now()
        row = FocusPlanModel(
            owner_id=self.owner_id,
            work_item_id=work_item_id,
            recommendation_id=payload.recommendation_id,
            source=payload.source.value,
            name=payload.name,
            is_template=payload.template,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self.db.add(row)
        await self.db.flush()
        row.segments = self._segment_rows(row.id, payload.segments)
        await self.db.flush()
        response = focus_plan_to_response(row)
        await complete_idempotency(
            self.db,
            owner_id=self.owner_id,
            scope="focus-plans:create",
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json", by_alias=True),
            resource_id=row.id,
        )
        await self.db.commit()
        return response

    async def get_focus_plan(self, focus_plan_id: UUID) -> FocusPlan:
        row = await self._focus_plan(focus_plan_id)
        if row is None:
            raise self._not_found("focus_plan_not_found", "Focus Plan not found")
        return focus_plan_to_response(row)

    async def list_focus_plans(
        self,
        *,
        limit: int,
        cursor: str | None,
        work_item_id: UUID | None,
        template_only: bool,
    ) -> FocusPlanPage:
        stmt = (
            select(FocusPlanModel)
            .options(selectinload(FocusPlanModel.segments))
            .where(
                FocusPlanModel.owner_id == self.owner_id,
                FocusPlanModel.deleted_at.is_(None),
            )
            .order_by(FocusPlanModel.created_at.desc(), FocusPlanModel.id.desc())
            .limit(limit + 1)
        )
        if work_item_id is not None:
            stmt = stmt.where(FocusPlanModel.work_item_id == work_item_id)
        if template_only:
            stmt = stmt.where(FocusPlanModel.is_template.is_(True))
        if cursor is not None:
            created_at, row_id = self._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    FocusPlanModel.created_at < created_at,
                    and_(FocusPlanModel.created_at == created_at, FocusPlanModel.id < row_id),
                )
            )
        rows = list((await self.db.scalars(stmt)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        )
        return FocusPlanPage(
            items=[focus_plan_to_response(row) for row in rows],
            page=PageMeta(has_more=has_more, next_cursor=next_cursor),
        )

    async def update_focus_plan(
        self,
        focus_plan_id: UUID,
        payload: UpdateFocusPlanRequest,
        if_match: str | None,
    ) -> FocusPlan:
        row = await self._focus_plan(focus_plan_id, lock=True)
        if row is None:
            raise self._not_found("focus_plan_not_found", "Focus Plan not found")
        require_etag(if_match, make_etag("focus-plan", row.id, row.version))
        changed = False
        if "name" in payload.model_fields_set and payload.name != row.name:
            row.name = payload.name or row.name
            changed = True
        if "template" in payload.model_fields_set and payload.template != row.is_template:
            if row.source != FocusPlanSource.TEMPLATE.value:
                raise ApiError(
                    409,
                    "focus_plan_source_conflict",
                    "Focus Plan source conflict",
                    "Only template-source plans can have template=true.",
                )
            if payload.template is False:
                raise ApiError(
                    409,
                    "focus_plan_source_conflict",
                    "Focus Plan source conflict",
                    "A template-source plan cannot be converted in place to a non-template plan.",
                )
        if "segments" in payload.model_fields_set and payload.segments is not None:
            target = await self._validate_plan_target(row.work_item_id)
            await self._validate_segments(payload.segments, target)
            row.segments.clear()
            await self.db.flush()
            row.segments.extend(self._segment_rows(row.id, payload.segments))
            changed = True
        if changed:
            row.updated_at = utc_now()
            row.version += 1
            await self.db.commit()
            row = await self._focus_plan(focus_plan_id)
            assert row is not None
        else:
            await self.db.commit()
        return focus_plan_to_response(row)

    async def delete_focus_plan(self, focus_plan_id: UUID, if_match: str | None) -> None:
        row = await self._focus_plan(focus_plan_id, lock=True)
        if row is None:
            raise self._not_found("focus_plan_not_found", "Focus Plan not found")
        require_etag(if_match, make_etag("focus-plan", row.id, row.version))
        deleted_at = utc_now()
        row.deleted_at = deleted_at
        row.updated_at = deleted_at
        row.version += 1
        await self.db.commit()

    async def _preferences(self) -> UserPreferences:
        preferences = await self.db.get(UserPreferences, self.owner_id)
        if preferences is None:
            raise ApiError(
                500,
                "preferences_missing",
                "Preferences missing",
                "User preferences are unavailable.",
            )
        return preferences

    async def _live_work_item(self, item_id: UUID, *, lock: bool = False) -> WorkItem | None:
        stmt = select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.owner_id == self.owner_id,
            WorkItem.deleted_at.is_(None),
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _characteristics_for(self, item: WorkItem) -> WorkCharacteristics | None:
        work_type = None
        if item.work_type_id is not None:
            work_type = await self.db.get(WorkType, item.work_type_id)
        return effective_characteristics(item, work_type)

    async def _sprint_children(self, sprint_id: UUID) -> list[SprintChild]:
        rows = list(
            (
                await self.db.scalars(
                    select(WorkItem)
                    .where(
                        WorkItem.owner_id == self.owner_id,
                        WorkItem.parent_id == sprint_id,
                        WorkItem.kind == WorkItemKind.CHORE.value,
                        WorkItem.deleted_at.is_(None),
                        WorkItem.status.not_in(_TERMINAL),
                        WorkItem.estimated_effort_seconds.is_not(None),
                        WorkItem.estimated_effort_seconds > 0,
                    )
                    .order_by(WorkItem.position, WorkItem.id)
                )
            ).all()
        )
        children: list[SprintChild] = []
        for row in rows:
            characteristics = await self._characteristics_for(row)
            if characteristics is None or row.estimated_effort_seconds is None:
                continue
            children.append(
                SprintChild(
                    id=row.id,
                    name=row.name,
                    estimate_seconds=row.estimated_effort_seconds,
                    characteristics=characteristics,
                )
            )
        return children

    async def _validate_plan_target(self, work_item_id: UUID | None) -> WorkItem | None:
        if work_item_id is None:
            return None
        row = await self._live_work_item(work_item_id)
        if row is None:
            raise self._not_found("work_item_not_found", "Work item not found")
        if row.kind == WorkItemKind.PROJECT.value:
            raise ApiError(
                422,
                "project_requires_next_action",
                "Project cannot be focused directly",
                "Focus Plans can target a Chore or Sprint, not a Project.",
            )
        return row

    async def _validate_segments(
        self,
        segments: list[FocusPlanSegmentInput],
        target: WorkItem | None,
    ) -> None:
        linked_ids = {
            segment.linked_work_item_id for segment in segments if segment.linked_work_item_id
        }
        if not linked_ids:
            return
        if target is None:
            raise ApiError(
                422,
                "invalid_focus_plan_link",
                "Invalid linked work item",
                "A generic Focus Plan cannot contain linked work-item segments.",
            )
        rows = list(
            (
                await self.db.scalars(
                    select(WorkItem).where(
                        WorkItem.id.in_(linked_ids),
                        WorkItem.owner_id == self.owner_id,
                        WorkItem.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        if set(by_id) != linked_ids:
            raise ApiError(
                422,
                "invalid_focus_plan_link",
                "Invalid linked work item",
                "Every linkedWorkItemId must reference a live caller-owned work item.",
            )
        if target.kind == WorkItemKind.CHORE.value:
            if any(row.id != target.id for row in rows):
                raise ApiError(
                    422,
                    "invalid_focus_plan_link",
                    "Invalid linked work item",
                    "A Chore plan can only link segments to that Chore.",
                )
        else:
            if any(
                row.kind != WorkItemKind.CHORE.value or row.parent_id != target.id for row in rows
            ):
                raise ApiError(
                    422,
                    "invalid_focus_plan_link",
                    "Invalid linked work item",
                    "A Sprint plan can only link segments to its direct Chores.",
                )

    async def _focus_plan(
        self, focus_plan_id: UUID, *, lock: bool = False
    ) -> FocusPlanModel | None:
        stmt = (
            select(FocusPlanModel)
            .options(selectinload(FocusPlanModel.segments))
            .where(
                FocusPlanModel.id == focus_plan_id,
                FocusPlanModel.owner_id == self.owner_id,
                FocusPlanModel.deleted_at.is_(None),
            )
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _segment_rows(
        focus_plan_id: UUID,
        segments: list[FocusPlanSegmentInput],
    ) -> list[FocusPlanSegmentModel]:
        return [
            FocusPlanSegmentModel(
                focus_plan_id=focus_plan_id,
                segment_index=index,
                kind=segment.kind.value,
                duration_mode=segment.duration_mode.value,
                target_seconds=segment.target_seconds,
                min_seconds=segment.min_seconds,
                max_seconds=segment.max_seconds,
                linked_work_item_id=segment.linked_work_item_id,
                optional=segment.optional,
                label=segment.label,
                instructions=segment.instructions,
            )
            for index, segment in enumerate(segments)
        ]

    @staticmethod
    def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
        raw = json.dumps([created_at.isoformat(), str(row_id)], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            created, row_id = json.loads(raw)
            return datetime.fromisoformat(created), UUID(row_id)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ApiError(
                422,
                "invalid_cursor",
                "Invalid cursor",
                "The pagination cursor is invalid.",
            ) from error

    @staticmethod
    def _not_found(code: str, title: str) -> ApiError:
        return ApiError(404, code, title, "The requested resource does not exist.")

    @staticmethod
    def _missing_context(detail: str) -> ApiError:
        return ApiError(
            422,
            "recommendation_context_incomplete",
            "Recommendation context incomplete",
            detail,
        )
