from uuid import uuid4

import pytest
from pydantic import ValidationError

from taskiller.core.config import Settings
from taskiller.main import create_app
from taskiller.work.schemas import (
    CreateWorkItemRequest,
    ReorderWorkItemRequest,
    UpdateWorkTypeRequest,
)


def test_round_three_paths_and_operation_ids_are_stable() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    expected = {
        "/api/v1/work-types": {"get": "listWorkTypes", "post": "createWorkType"},
        "/api/v1/work-types/{workTypeId}": {
            "get": "getWorkType",
            "patch": "updateWorkType",
            "delete": "deleteWorkType",
        },
        "/api/v1/work-items": {"get": "listWorkItems", "post": "createWorkItem"},
        "/api/v1/work-items/{workItemId}": {
            "get": "getWorkItem",
            "patch": "updateWorkItem",
            "delete": "deleteWorkItem",
        },
        "/api/v1/work-items/{workItemId}/children": {"get": "listWorkItemChildren"},
        "/api/v1/work-items/{workItemId}/tree": {"get": "getWorkItemTree"},
        "/api/v1/work-items/{workItemId}/reorder": {"post": "reorderWorkItem"},
        "/api/v1/projects/{projectId}/next-action": {"get": "getProjectNextAction"},
    }
    for path, operations in expected.items():
        assert path in paths
        for method, operation_id in operations.items():
            assert paths[path][method]["operationId"] == operation_id


def test_create_mutations_document_required_idempotency_key() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    operations = [
        paths["/api/v1/work-types"]["post"],
        paths["/api/v1/work-items"]["post"],
        paths["/api/v1/work-items/{workItemId}/reorder"]["post"],
    ]
    for operation in operations:
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True


def test_sprint_can_be_parsed_without_parent_but_domain_service_will_reject_it() -> None:
    payload = CreateWorkItemRequest(kind="sprint", name="Backend")
    assert payload.parent_id is None


def test_create_request_rejects_inverted_time_range() -> None:
    with pytest.raises(ValidationError):
        CreateWorkItemRequest(
            kind="project",
            name="Taskiller",
            plannedStartAt="2026-09-29T12:00:00Z",
            deadlineAt="2026-09-28T12:00:00Z",
        )


def test_reorder_rejects_two_anchors() -> None:
    with pytest.raises(ValidationError):
        ReorderWorkItemRequest(beforeId=uuid4(), afterId=uuid4())


def test_work_type_update_rejects_null_display_name() -> None:
    with pytest.raises(ValidationError):
        UpdateWorkTypeRequest(displayName=None)


def test_work_item_datetimes_require_an_offset() -> None:
    with pytest.raises(ValidationError):
        CreateWorkItemRequest(
            kind="chore",
            name="Offset required",
            plannedStartAt="2026-09-28T12:00:00",
        )
