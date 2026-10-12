"""Portable import input-validation tests; no database required."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from taskiller.django_api.portable_import import PortableDocument


def _item(source_id: str, kind: str, parent: str | None = None) -> dict[str, object]:
    return {
        "sourceId": source_id,
        "parentSourceId": parent,
        "workTypeSlug": None,
        "kind": kind,
        "name": source_id,
        "position": 0,
    }


def _document(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "format": "taskiller.portable.work.v1",
        "items": items,
        "workTypes": [],
    }


def test_valid_project_sprint_chore_tree() -> None:
    doc = PortableDocument.model_validate(
        _document([_item("a", "project"), _item("b", "sprint", "a"), _item("c", "chore", "b")])
    )
    assert len(doc.items) == 3


@pytest.mark.parametrize(
    "items",
    [
        [_item("a", "chore"), _item("a", "chore")],
        [_item("a", "chore", "missing")],
        [_item("a", "chore", "a")],
        [_item("a", "chore"), _item("b", "sprint", "a")],
        [_item("a", "project", "b"), _item("b", "project", "a")],
    ],
)
def test_invalid_hierarchy_rejected(items: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        PortableDocument.model_validate(_document(items))
