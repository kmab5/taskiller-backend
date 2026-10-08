from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.focus_service import DjangoFocusService


def test_focus_cursor_round_trip() -> None:
    created = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    row_id = uuid4()
    cursor = DjangoFocusService._encode_cursor(created, row_id)
    parsed_created, parsed_id = DjangoFocusService._decode_cursor(cursor)
    assert parsed_created == created
    assert parsed_id == row_id


def test_invalid_focus_cursor_uses_stable_code() -> None:
    with pytest.raises(TaskillerAPIError) as error:
        DjangoFocusService._decode_cursor("invalid")
    assert error.value.code == "invalid_cursor"
