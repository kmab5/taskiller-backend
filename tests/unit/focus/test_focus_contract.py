from uuid import uuid4

import pytest
from pydantic import ValidationError

from taskiller.core.config import Settings
from taskiller.focus.schemas import CreateFocusPlanRequest, FocusPlanSegmentInput
from taskiller.main import create_app


def test_round_four_paths_and_operation_ids_are_stable() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    expected = {
        "/api/v1/focus-plan-recommendations": {"post": "createFocusPlanRecommendation"},
        "/api/v1/focus-plan-recommendations/{recommendationId}": {
            "get": "getFocusPlanRecommendation",
        },
        "/api/v1/focus-plans": {"get": "listFocusPlans", "post": "createFocusPlan"},
        "/api/v1/focus-plans/{focusPlanId}": {
            "get": "getFocusPlan",
            "patch": "updateFocusPlan",
            "delete": "deleteFocusPlan",
        },
    }
    for path, operations in expected.items():
        assert path in paths
        for method, operation_id in operations.items():
            assert paths[path][method]["operationId"] == operation_id


def test_focus_creates_require_idempotency_key() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    operations = [
        paths["/api/v1/focus-plan-recommendations"]["post"],
        paths["/api/v1/focus-plans"]["post"],
    ]
    for operation in operations:
        header = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
        assert header["required"] is True


def test_fixed_segment_requires_target() -> None:
    with pytest.raises(ValidationError):
        FocusPlanSegmentInput(kind="work", durationMode="fixed", optional=False)


def test_segment_rejects_inverted_flexible_range() -> None:
    with pytest.raises(ValidationError):
        FocusPlanSegmentInput(
            kind="work",
            durationMode="flexible",
            targetSeconds=1200,
            minSeconds=1500,
            maxSeconds=1800,
            optional=False,
        )


def test_break_cannot_link_work_item() -> None:
    with pytest.raises(ValidationError):
        FocusPlanSegmentInput(
            kind="break",
            durationMode="fixed",
            targetSeconds=300,
            linkedWorkItemId=uuid4(),
            optional=True,
        )


def test_recommendation_source_requires_recommendation_id() -> None:
    with pytest.raises(ValidationError):
        CreateFocusPlanRequest(
            source="recommendation",
            name="Recommended",
            segments=[
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1800,
                    "optional": False,
                },
            ],
        )


def test_templates_are_unbound_and_cannot_link_work_items() -> None:
    with pytest.raises(ValidationError):
        CreateFocusPlanRequest(
            source="template",
            template=True,
            workItemId=uuid4(),
            name="Reusable",
            segments=[
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1800,
                    "optional": False,
                },
            ],
        )
