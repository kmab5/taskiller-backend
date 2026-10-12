"""Atomic import of the Taskiller portable v1 work document."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from django.db import transaction
from pydantic import Field, ValidationError, model_validator

from taskiller.api.models import ApiModel
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.idempotency import claim_idempotency, complete_idempotency
from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_api.work_service import DjangoWorkService
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    CreateWorkTypeRequest,
    PartialWorkCharacteristics,
    WorkCharacteristics,
    WorkItemKind,
)

FORMAT = "taskiller.portable.work.v1"


class PortableType(ApiModel):
    slug: str
    display_name: str
    description: str | None = None
    characteristics: WorkCharacteristics


class PortableItem(ApiModel):
    source_id: str = Field(min_length=1, max_length=200)
    parent_source_id: str | None = None
    work_type_slug: str | None = None
    kind: WorkItemKind
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    priority: int | None = Field(default=None, ge=0, le=5)
    position: int = 0
    estimated_effort_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    planned_start_at: str | None = None
    deadline_at: str | None = None
    target_start_date: str | None = None
    target_end_date: str | None = None
    characteristic_overrides: PartialWorkCharacteristics | None = None


class PortableDocument(ApiModel):
    format: str
    created_at: str = ""
    root_source_id: str | None = None
    work_types: list[PortableType] = Field(max_length=1500)
    items: list[PortableItem] = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def valid_references(self) -> PortableDocument:
        if self.format != FORMAT:
            raise ValueError("Unsupported Taskiller portable format")
        ids = [item.source_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate source IDs")
        slugs = [item.slug for item in self.work_types]
        if len(set(slugs)) != len(slugs):
            raise ValueError("Duplicate Work Type slugs")
        items = {item.source_id: item for item in self.items}
        for item in self.items:
            if item.parent_source_id is not None:
                parent = items.get(item.parent_source_id)
                if parent is None:
                    raise ValueError(f"Missing parent for {item.name}")
                if parent.kind is WorkItemKind.CHORE or item.kind is WorkItemKind.PROJECT:
                    raise ValueError(f"Invalid hierarchy for {item.name}")
                if item.kind is WorkItemKind.SPRINT and parent.kind is not WorkItemKind.PROJECT:
                    raise ValueError(f"Sprint needs a Project parent: {item.name}")
            seen: set[str] = set()
            current: PortableItem | None = item
            while current is not None:
                if current.source_id in seen:
                    raise ValueError("Work hierarchy contains a cycle")
                seen.add(current.source_id)
                current = items.get(current.parent_source_id) if current.parent_source_id else None
        return self


def _subkey(key: str, category: str, source: str) -> str:
    digest = hashlib.sha256(f"{key}:{category}:{source}".encode()).hexdigest()
    return f"portable-{digest}"


def import_portable_document(owner_id: UUID, raw: Any, key: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskillerAPIError(422, "validation_error", "Invalid import", "Expected a JSON object")
    try:
        document = PortableDocument.model_validate(raw)
    except ValidationError as exc:
        raise TaskillerAPIError(
            422, "validation_error", "Invalid portable document", str(exc)[:1000]
        ) from exc

    service = DjangoWorkService(owner_id)
    payload = document.model_dump(mode="json", by_alias=True)
    with transaction.atomic():
        replay = claim_idempotency(
            owner_id=owner_id,
            scope="portable:import:v1",
            key=key,
            request_payload=payload,
            ttl_hours=taskiller_settings().idempotency_ttl_hours,
        )
        if replay is not None:
            return replay.response_body

        available = {row["slug"]: row["id"] for row in service.list_work_types()["items"]}
        declared = {item.slug: item for item in document.work_types}
        for slug in {item.work_type_slug for item in document.items if item.work_type_slug}:
            if slug in available:
                continue
            definition = declared.get(slug)
            if definition is None:
                raise TaskillerAPIError(
                    422,
                    "work_type_missing",
                    "Missing Work Type",
                    f"Work Type {slug} is not defined.",
                )
            try:
                created = service.create_work_type(
                    CreateWorkTypeRequest.model_validate(
                        definition.model_dump(mode="json", by_alias=True)
                    ),
                    _subkey(key, "type", slug),
                )
            except (TaskillerAPIError, ValidationError) as exc:
                raise TaskillerAPIError(
                    422, "import_type_invalid", "Invalid Work Type", f"{slug}: {exc}"
                ) from exc
            available[slug] = created["id"]

        pending = {item.source_id: item for item in document.items}
        imported: dict[str, str] = {}
        while pending:
            advanced = False
            for source_id, item in list(pending.items()):
                if item.parent_source_id and item.parent_source_id not in imported:
                    continue
                input_data: dict[str, Any] = {
                    "kind": item.kind.value,
                    "name": item.name,
                    "description": item.description,
                    "status": "draft",
                    "parentId": imported.get(item.parent_source_id)
                    if item.parent_source_id
                    else None,
                    "workTypeId": available.get(item.work_type_slug)
                    if item.work_type_slug
                    else None,
                    "priority": item.priority,
                    "estimatedEffortSeconds": item.estimated_effort_seconds,
                    "plannedStartAt": item.planned_start_at,
                    "deadlineAt": item.deadline_at,
                    "targetStartDate": item.target_start_date,
                    "targetEndDate": item.target_end_date,
                    "characteristicOverrides": (
                        item.characteristic_overrides.model_dump(mode="json", by_alias=True)
                        if item.characteristic_overrides is not None
                        else None
                    ),
                }
                try:
                    validated = CreateWorkItemRequest.model_validate(input_data)
                    created = service.create_work_item(validated, _subkey(key, "item", source_id))
                except (TaskillerAPIError, ValidationError) as exc:
                    raise TaskillerAPIError(
                        422,
                        "portable_import_item_failed",
                        "Import rejected",
                        f"Could not import {item.kind.value} '{item.name}': {exc}",
                        meta={"sourceId": source_id, "name": item.name},
                    ) from exc
                imported[source_id] = str(created["id"])
                del pending[source_id]
                advanced = True
            if not advanced:
                raise TaskillerAPIError(
                    422, "invalid_hierarchy", "Invalid hierarchy", "No importable root found"
                )

        response: dict[str, Any] = {"created": len(imported), "idMap": imported, "atomic": True}
        complete_idempotency(
            owner_id=owner_id,
            scope="portable:import:v1",
            key=key,
            response_status=201,
            response_body=response,
            resource_id=None,
        )
        return response
