from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Q
from pydantic import BaseModel, ValidationError

from taskiller.core.time import utc_now
from taskiller.django_api.analytics_service import DjangoAnalyticsService
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.idempotency import claim_idempotency, complete_idempotency
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_domain.models import (
    FocusPlan,
    FocusPlanRecommendation,
    FocusPlanSegment,
    UserPreferences,
    WorkItem,
    WorkType,
)
from taskiller.focus.engine import (
    ENGINE_VERSION,
    EnginePreferences,
    SprintChild,
    generate_chore_recommendation,
    generate_sprint_recommendation,
)
from taskiller.focus.schemas import (
    CreateFocusPlanRequest,
    CreateRecommendationRequest,
    FocusPlanSegmentInput,
    FocusPlanSource,
    RecommendationProvenance,
    RecommendationReasonLabel,
    RecommendationStrategy,
    UpdateFocusPlanRequest,
)
from taskiller.users.etag import make_etag
from taskiller.work.presenters import effective_characteristics
from taskiller.work.schemas import WorkCharacteristics, WorkItemKind, WorkItemStatus

_TERMINAL = {
    WorkItemStatus.COMPLETED.value,
    WorkItemStatus.CANCELLED.value,
    WorkItemStatus.ARCHIVED.value,
}


def validate_payload[T: BaseModel](model: type[T], data: Any) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "One or more request values are invalid.",
            meta={
                "errors": [
                    {
                        "type": item.get("type"),
                        "loc": ["body", *item.get("loc", ())],
                        "msg": item.get("msg"),
                    }
                    for item in exc.errors()
                ]
            },
        ) from exc


def require_idempotency_key(value: str | None) -> str:
    key = value or ""
    if not 8 <= len(key) <= 200:
        raise TaskillerAPIError(
            422,
            "validation_error",
            "Request validation failed",
            "Idempotency-Key must be between 8 and 200 characters.",
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


def _recommendation_response(row: FocusPlanRecommendation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workItemId": str(row.work_item_id),
        "engineVersion": row.engine_version,
        "provenance": row.provenance,
        "plan": row.plan_snapshot_json,
        "reasons": row.reasons_json,
        "createdAt": row.created_at.isoformat(),
    }


def _segment_response(row: FocusPlanSegment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "index": row.segment_index,
        "kind": row.kind,
        "durationMode": row.duration_mode,
        "targetSeconds": row.target_seconds,
        "minSeconds": row.min_seconds,
        "maxSeconds": row.max_seconds,
        "linkedWorkItemId": (
            str(row.linked_work_item_id) if row.linked_work_item_id is not None else None
        ),
        "optional": row.optional,
        "label": row.label,
        "instructions": row.instructions,
    }


def _focus_plan_response(row: FocusPlan) -> dict[str, Any]:
    segments = list(FocusPlanSegment.objects.filter(focus_plan_id=row.id).order_by("segment_index"))
    return {
        "id": str(row.id),
        "workItemId": str(row.work_item_id) if row.work_item_id is not None else None,
        "recommendationId": (
            str(row.recommendation_id) if row.recommendation_id is not None else None
        ),
        "source": row.source,
        "name": row.name,
        "template": row.is_template,
        "segments": [_segment_response(segment) for segment in segments],
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "version": row.version,
    }


async def _personalization_signal_async(
    owner_id: UUID,
    work_type_id: UUID,
    work_type_slug: str,
) -> object | None:
    return await DjangoAnalyticsService(owner_id=owner_id).personalization_signal(
        work_type_id=work_type_id,
        work_type_slug=work_type_slug,
    )


class DjangoFocusService:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.idempotency_ttl_hours = taskiller_settings().idempotency_ttl_hours

    def create_recommendation(
        self,
        payload: CreateRecommendationRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_body = _dump(payload)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope="focus-plan-recommendations:create",
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            work_item = (
                WorkItem.objects.select_for_update()
                .filter(
                    id=payload.work_item_id,
                    owner_id=self.owner_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if work_item is None:
                raise self._not_found("work_item_not_found", "Work item not found")
            if work_item.status in _TERMINAL:
                raise TaskillerAPIError(
                    409,
                    "work_item_not_executable",
                    "Work item is not executable",
                    "Completed, cancelled, or archived work cannot receive a new recommendation.",
                )
            if WorkItemKind(work_item.kind) is WorkItemKind.PROJECT:
                raise TaskillerAPIError(
                    422,
                    "project_requires_next_action",
                    "Project cannot be focused directly",
                    (
                        "Resolve the Project next action and request a Focus "
                        "Plan for its Sprint or Chore."
                    ),
                )

            preferences = UserPreferences.objects.filter(user_id=self.owner_id).first()
            if preferences is None:
                raise TaskillerAPIError(
                    500,
                    "preferences_missing",
                    "Preferences missing",
                    "User preferences are unavailable.",
                )

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
                characteristics = self._characteristics_for(work_item)
                if characteristics is None:
                    raise self._missing_context(
                        "The Chore needs a Work Type or complete characteristic overrides."
                    )
                if work_item.work_type_id is not None:
                    work_type = WorkType.objects.filter(id=work_item.work_type_id).first()
                    if work_type is not None:
                        personalization_signal = async_to_sync(_personalization_signal_async)(
                            self.owner_id,
                            work_type.id,
                            work_type.slug,
                        )
                        if personalization_signal is not None:
                            engine_preferences = EnginePreferences(
                                strategy=engine_preferences.strategy,
                                work_block_min_seconds=engine_preferences.work_block_min_seconds,
                                work_block_max_seconds=engine_preferences.work_block_max_seconds,
                                personal_work_block_seconds=(personalization_signal.target_seconds),
                                personal_sample_size=personalization_signal.sample_size,
                            )
                effort = work_item.estimated_effort_seconds or payload.available_time_seconds
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
                            mode="json",
                            by_alias=True,
                        ),
                    }
                }
            else:
                children = self._sprint_children(work_item.id)
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
                                    mode="json",
                                    by_alias=True,
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
            row = FocusPlanRecommendation.objects.create(
                id=uuid4(),
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
                        "preferredWorkBlockMinSeconds": (engine_preferences.work_block_min_seconds),
                        "preferredWorkBlockMaxSeconds": (engine_preferences.work_block_max_seconds),
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
                plan_snapshot_json=generated.plan.model_dump(
                    mode="json",
                    by_alias=True,
                ),
                reasons_json=[
                    reason.model_dump(mode="json", by_alias=True) for reason in generated.reasons
                ],
                created_at=now,
            )
            response = _recommendation_response(row)
            complete_idempotency(
                owner_id=self.owner_id,
                scope="focus-plan-recommendations:create",
                key=idempotency_key,
                response_status=201,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_recommendation(self, recommendation_id: UUID) -> dict[str, Any]:
        row = FocusPlanRecommendation.objects.filter(
            id=recommendation_id,
            owner_id=self.owner_id,
        ).first()
        if row is None:
            raise self._not_found(
                "recommendation_not_found",
                "Recommendation not found",
            )
        return _recommendation_response(row)

    def create_focus_plan(
        self,
        payload: CreateFocusPlanRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_body = _dump(payload)

        with transaction.atomic():
            replay = claim_idempotency(
                owner_id=self.owner_id,
                scope="focus-plans:create",
                key=idempotency_key,
                request_payload=request_body,
                ttl_hours=self.idempotency_ttl_hours,
            )
            if replay is not None:
                return replay.response_body

            work_item_id = payload.work_item_id
            if payload.recommendation_id is not None:
                recommendation = FocusPlanRecommendation.objects.filter(
                    id=payload.recommendation_id,
                    owner_id=self.owner_id,
                ).first()
                if recommendation is None:
                    raise self._not_found(
                        "recommendation_not_found",
                        "Recommendation not found",
                    )
                if work_item_id is None:
                    work_item_id = recommendation.work_item_id
                elif work_item_id != recommendation.work_item_id:
                    raise TaskillerAPIError(
                        422,
                        "recommendation_work_item_mismatch",
                        "Recommendation does not match work item",
                        "recommendationId and workItemId must refer to the same work item.",
                    )

            target = self._validate_plan_target(work_item_id)
            self._validate_segments(payload.segments, target)

            now = utc_now()
            focus_plan_id = uuid4()
            row = FocusPlan.objects.create(
                id=focus_plan_id,
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
            self._replace_segments(row.id, payload.segments)
            response = _focus_plan_response(row)
            complete_idempotency(
                owner_id=self.owner_id,
                scope="focus-plans:create",
                key=idempotency_key,
                response_status=201,
                response_body=response,
                resource_id=row.id,
            )
            return response

    def get_focus_plan(self, focus_plan_id: UUID) -> dict[str, Any]:
        row = self._focus_plan(focus_plan_id)
        if row is None:
            raise self._not_found("focus_plan_not_found", "Focus Plan not found")
        return _focus_plan_response(row)

    def list_focus_plans(
        self,
        *,
        limit: int,
        cursor: str | None,
        work_item_id: UUID | None,
        template_only: bool,
    ) -> dict[str, Any]:
        query = FocusPlan.objects.filter(
            owner_id=self.owner_id,
            deleted_at__isnull=True,
        )
        if work_item_id is not None:
            query = query.filter(work_item_id=work_item_id)
        if template_only:
            query = query.filter(is_template=True)
        if cursor is not None:
            created_at, row_id = self._decode_cursor(cursor)
            query = query.filter(
                Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=row_id)
            )

        rows = list(query.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        )
        return {
            "items": [_focus_plan_response(row) for row in rows],
            "page": {
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
        }

    def update_focus_plan(
        self,
        focus_plan_id: UUID,
        payload: UpdateFocusPlanRequest,
        if_match: str | None,
    ) -> dict[str, Any]:
        with transaction.atomic():
            row = self._focus_plan(focus_plan_id, lock=True)
            if row is None:
                raise self._not_found(
                    "focus_plan_not_found",
                    "Focus Plan not found",
                )
            require_etag(
                if_match,
                make_etag("focus-plan", row.id, row.version),
            )
            changed = False

            if "name" in payload.model_fields_set and payload.name != row.name:
                assert payload.name is not None
                row.name = payload.name
                changed = True

            if "template" in payload.model_fields_set and payload.template != row.is_template:
                if row.source != FocusPlanSource.TEMPLATE.value:
                    raise TaskillerAPIError(
                        409,
                        "focus_plan_source_conflict",
                        "Focus Plan source conflict",
                        "Only template-source plans can have template=true.",
                    )
                if payload.template is False:
                    raise TaskillerAPIError(
                        409,
                        "focus_plan_source_conflict",
                        "Focus Plan source conflict",
                        (
                            "A template-source plan cannot be converted in place to "
                            "a non-template plan."
                        ),
                    )

            if "segments" in payload.model_fields_set and payload.segments is not None:
                target = self._validate_plan_target(row.work_item_id)
                self._validate_segments(payload.segments, target)
                self._replace_segments(row.id, payload.segments)
                changed = True

            if changed:
                row.updated_at = utc_now()
                row.version += 1
                row.save(update_fields=["name", "updated_at", "version"])

            return _focus_plan_response(row)

    def delete_focus_plan(
        self,
        focus_plan_id: UUID,
        if_match: str | None,
    ) -> None:
        with transaction.atomic():
            row = self._focus_plan(focus_plan_id, lock=True)
            if row is None:
                raise self._not_found(
                    "focus_plan_not_found",
                    "Focus Plan not found",
                )
            require_etag(
                if_match,
                make_etag("focus-plan", row.id, row.version),
            )
            deleted_at = utc_now()
            row.deleted_at = deleted_at
            row.updated_at = deleted_at
            row.version += 1
            row.save(update_fields=["deleted_at", "updated_at", "version"])

    def _characteristics_for(
        self,
        item: WorkItem,
    ) -> WorkCharacteristics | None:
        work_type = (
            WorkType.objects.filter(id=item.work_type_id).first()
            if item.work_type_id is not None
            else None
        )
        return effective_characteristics(item, work_type)  # type: ignore[arg-type]

    def _sprint_children(self, sprint_id: UUID) -> list[SprintChild]:
        rows = list(
            WorkItem.objects.filter(
                owner_id=self.owner_id,
                parent_id=sprint_id,
                kind=WorkItemKind.CHORE.value,
                deleted_at__isnull=True,
                estimated_effort_seconds__isnull=False,
                estimated_effort_seconds__gt=0,
            )
            .exclude(status__in=_TERMINAL)
            .order_by("position", "id")
        )
        children: list[SprintChild] = []
        for row in rows:
            characteristics = self._characteristics_for(row)
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

    def _validate_plan_target(
        self,
        work_item_id: UUID | None,
    ) -> WorkItem | None:
        if work_item_id is None:
            return None
        row = WorkItem.objects.filter(
            id=work_item_id,
            owner_id=self.owner_id,
            deleted_at__isnull=True,
        ).first()
        if row is None:
            raise self._not_found("work_item_not_found", "Work item not found")
        if row.kind == WorkItemKind.PROJECT.value:
            raise TaskillerAPIError(
                422,
                "project_requires_next_action",
                "Project cannot be focused directly",
                "Focus Plans can target a Chore or Sprint, not a Project.",
            )
        return row

    def _validate_segments(
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
            raise TaskillerAPIError(
                422,
                "invalid_focus_plan_link",
                "Invalid linked work item",
                "A generic Focus Plan cannot contain linked work-item segments.",
            )

        rows = list(
            WorkItem.objects.filter(
                id__in=linked_ids,
                owner_id=self.owner_id,
                deleted_at__isnull=True,
            )
        )
        by_id = {row.id: row for row in rows}
        if set(by_id) != linked_ids:
            raise TaskillerAPIError(
                422,
                "invalid_focus_plan_link",
                "Invalid linked work item",
                "Every linkedWorkItemId must reference a live caller-owned work item.",
            )

        if target.kind == WorkItemKind.CHORE.value:
            if any(row.id != target.id for row in rows):
                raise TaskillerAPIError(
                    422,
                    "invalid_focus_plan_link",
                    "Invalid linked work item",
                    "A Chore plan can only link segments to that Chore.",
                )
        elif any(
            row.kind != WorkItemKind.CHORE.value or row.parent_id != target.id for row in rows
        ):
            raise TaskillerAPIError(
                422,
                "invalid_focus_plan_link",
                "Invalid linked work item",
                "A Sprint plan can only link segments to its direct Chores.",
            )

    def _focus_plan(
        self,
        focus_plan_id: UUID,
        *,
        lock: bool = False,
    ) -> FocusPlan | None:
        query = FocusPlan.objects.filter(
            id=focus_plan_id,
            owner_id=self.owner_id,
            deleted_at__isnull=True,
        )
        if lock:
            query = query.select_for_update()
        return query.first()

    @staticmethod
    def _replace_segments(
        focus_plan_id: UUID,
        segments: list[FocusPlanSegmentInput],
    ) -> None:
        FocusPlanSegment.objects.filter(focus_plan_id=focus_plan_id).delete()
        FocusPlanSegment.objects.bulk_create(
            [
                FocusPlanSegment(
                    id=uuid4(),
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
        )

    @staticmethod
    def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
        raw = json.dumps(
            [created_at.isoformat(), str(row_id)],
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            created, row_id = json.loads(raw)
            return datetime.fromisoformat(created), UUID(row_id)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise TaskillerAPIError(
                422,
                "invalid_cursor",
                "Invalid cursor",
                "The pagination cursor is invalid.",
            ) from exc

    @staticmethod
    def _not_found(code: str, title: str) -> TaskillerAPIError:
        return TaskillerAPIError(
            404,
            code,
            title,
            "The requested resource does not exist.",
        )

    @staticmethod
    def _missing_context(detail: str) -> TaskillerAPIError:
        return TaskillerAPIError(
            422,
            "recommendation_context_incomplete",
            "Recommendation context incomplete",
            detail,
        )
