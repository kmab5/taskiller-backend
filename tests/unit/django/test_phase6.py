from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.execution_service import DjangoExecutionService


def test_execution_cursor_round_trip() -> None:
    at = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    row_id = uuid4()
    cursor = DjangoExecutionService._encode_cursor(at, row_id)
    parsed_at, parsed_id = DjangoExecutionService._decode_cursor(cursor)
    assert parsed_at == at
    assert parsed_id == row_id


def test_invalid_execution_cursor_uses_stable_problem() -> None:
    with pytest.raises(TaskillerAPIError) as error:
        DjangoExecutionService._decode_cursor("invalid")
    assert error.value.code == "invalid_cursor"
