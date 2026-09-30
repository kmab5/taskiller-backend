from uuid import uuid4

import pytest
from pydantic import ValidationError

from taskiller.core.config import Settings
from taskiller.execution.schemas import CreateSessionEventRequest
from taskiller.main import create_app


def test_round_five_paths_and_operation_ids_are_stable() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    expected = {
        "/api/v1/execution-sessions": {
            "get": "listExecutionSessions",
            "post": "startExecutionSession",
        },
        "/api/v1/execution-sessions/active": {"get": "getActiveExecutionSession"},
        "/api/v1/execution-sessions/{executionSessionId}": {"get": "getExecutionSession"},
        "/api/v1/execution-sessions/{executionSessionId}/events": {
            "get": "listExecutionSessionEvents",
            "post": "appendExecutionSessionEvent",
        },
        "/api/v1/execution-sessions/{executionSessionId}/review": {
            "get": "getExecutionSessionReview",
            "put": "upsertExecutionSessionReview",
        },
    }
    for path, operations in expected.items():
        assert path in paths
        for method, operation_id in operations.items():
            assert paths[path][method]["operationId"] == operation_id


def test_session_start_and_event_write_require_idempotency_keys() -> None:
    paths = create_app(Settings(_env_file=None)).openapi()["paths"]
    operations = [
        paths["/api/v1/execution-sessions"]["post"],
        paths["/api/v1/execution-sessions/{executionSessionId}/events"]["post"],
        paths["/api/v1/execution-sessions/{executionSessionId}/review"]["put"],
    ]
    for operation in operations:
        header = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
        assert header["required"] is True


def test_event_write_exposes_if_match_for_cross_device_conflicts() -> None:
    operation = create_app(Settings(_env_file=None)).openapi()["paths"][
        "/api/v1/execution-sessions/{executionSessionId}/events"
    ]["post"]
    header = next(p for p in operation["parameters"] if p["name"] == "If-Match")
    assert header["required"] is False


def test_segment_event_requires_segment_index() -> None:
    with pytest.raises(ValidationError):
        CreateSessionEventRequest(type="segment_completed")


def test_non_segment_event_rejects_segment_index() -> None:
    with pytest.raises(ValidationError):
        CreateSessionEventRequest(type="paused", segmentIndex=0)


def test_client_cannot_create_session_started_event() -> None:
    with pytest.raises(ValidationError):
        CreateSessionEventRequest(type="session_started")


def test_work_item_completed_payload_accepts_future_structured_data() -> None:
    chore_id = uuid4()
    event = CreateSessionEventRequest(
        type="work_item_completed", payload={"workItemId": str(chore_id), "source": "timer"}
    )
    assert event.payload["workItemId"] == str(chore_id)


def test_client_occurred_at_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        CreateSessionEventRequest(type="paused", clientOccurredAt="2026-09-28T10:00:00")
