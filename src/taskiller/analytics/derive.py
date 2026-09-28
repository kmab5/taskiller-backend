from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

_BREAK_KINDS = {"break", "long_break"}
_WORK_KINDS = {"work", "retrieval", "review", "planning"}


@dataclass(frozen=True, slots=True)
class EventRecord:
    type: str
    occurred_at: datetime
    segment_index: int | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DerivedInterval:
    category: str
    start: datetime
    end: datetime
    session_id: UUID
    segment_index: int | None = None
    work_item_id: UUID | None = None

    @property
    def seconds(self) -> int:
        return max(0, round((self.end - self.start).total_seconds()))


@dataclass(slots=True)
class DerivedSessionMetrics:
    session_id: UUID
    intervals: list[DerivedInterval] = field(default_factory=list)
    active_work_seconds: int = 0
    break_seconds: int = 0
    paused_seconds: int = 0
    uninterrupted_work_seconds: list[int] = field(default_factory=list)
    work_item_active_seconds: dict[UUID, int] = field(default_factory=dict)
    required_segments_planned: int = 0
    required_segments_completed: int = 0
    completed_work_items: list[tuple[UUID, datetime]] = field(default_factory=list)


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _segment(plan_segments: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if index < 0 or index >= len(plan_segments):
        return None
    return plan_segments[index]


def _segment_category(segment: dict[str, Any] | None) -> str | None:
    if segment is None:
        return None
    kind = str(segment.get("kind", ""))
    if kind in _WORK_KINDS:
        return "active_work"
    if kind in _BREAK_KINDS:
        return "break"
    return None


def _segment_work_item_id(segment: dict[str, Any] | None, session_work_item_id: UUID) -> UUID:
    if segment is None:
        return session_work_item_id
    return _uuid_or_none(segment.get("linkedWorkItemId")) or session_work_item_id


def _clip_interval(
    interval: DerivedInterval, window_start: datetime, window_end: datetime
) -> DerivedInterval | None:
    start = max(interval.start, window_start)
    end = min(interval.end, window_end)
    if end <= start:
        return None
    return DerivedInterval(
        category=interval.category,
        start=start,
        end=end,
        session_id=interval.session_id,
        segment_index=interval.segment_index,
        work_item_id=interval.work_item_id,
    )


def derive_session_metrics(
    *,
    session_id: UUID,
    session_work_item_id: UUID,
    plan_snapshot: dict[str, Any],
    events: list[EventRecord],
    session_started_at: datetime,
    ended_at: datetime | None,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
) -> DerivedSessionMetrics:
    raw_segments = plan_snapshot.get("segments", [])
    plan_segments = [dict(item) for item in raw_segments if isinstance(item, dict)]
    result = DerivedSessionMetrics(session_id=session_id)
    result.required_segments_planned = sum(
        1 for item in plan_segments if not bool(item.get("optional", False))
    )

    current_index = 0
    active_since: datetime | None = None
    active_category: str | None = None
    active_work_item_id: UUID | None = None
    pause_since: datetime | None = None
    resume_active = False
    completed_required_indices: set[int] = set()
    full_intervals: list[DerivedInterval] = []

    def close_active(at: datetime) -> None:
        nonlocal active_since
        if active_since is None or active_category is None or at <= active_since:
            active_since = None
            return
        full_intervals.append(
            DerivedInterval(
                category=active_category,
                start=active_since,
                end=at,
                session_id=session_id,
                segment_index=current_index,
                work_item_id=active_work_item_id,
            )
        )
        active_since = None

    def close_pause(at: datetime) -> None:
        nonlocal pause_since
        if pause_since is None or at <= pause_since:
            pause_since = None
            return
        full_intervals.append(
            DerivedInterval(
                category="paused",
                start=pause_since,
                end=at,
                session_id=session_id,
            )
        )
        pause_since = None

    for event in sorted(events, key=lambda item: item.occurred_at):
        at = event.occurred_at
        if at < session_started_at:
            continue
        if event.type in {"segment_started", "break_started"}:
            if event.segment_index is not None:
                current_index = event.segment_index
            segment = _segment(plan_segments, current_index)
            active_category = _segment_category(segment)
            active_work_item_id = _segment_work_item_id(segment, session_work_item_id)
            active_since = at if active_category is not None else None
            continue
        if event.type == "paused":
            resume_active = active_since is not None
            close_active(at)
            pause_since = at
            continue
        if event.type == "resumed":
            close_pause(at)
            if resume_active:
                segment = _segment(plan_segments, current_index)
                active_category = _segment_category(segment)
                active_work_item_id = _segment_work_item_id(segment, session_work_item_id)
                active_since = at if active_category is not None else None
            resume_active = False
            continue
        if event.type in {"segment_completed", "break_ended", "segment_skipped"}:
            close_active(at)
            index = event.segment_index if event.segment_index is not None else current_index
            segment = _segment(plan_segments, index)
            if (
                event.type != "segment_skipped"
                and segment is not None
                and not bool(segment.get("optional", False))
            ):
                completed_required_indices.add(index)
            current_index = index + 1
            active_category = None
            active_work_item_id = None
            resume_active = False
            continue
        if event.type == "work_item_completed":
            target = _uuid_or_none(event.payload.get("workItemId"))
            if target is None:
                segment = _segment(plan_segments, current_index)
                target = _segment_work_item_id(segment, session_work_item_id)
            result.completed_work_items.append((target, at))
            continue
        if event.type in {"session_completed", "session_abandoned"}:
            close_active(at)
            close_pause(at)
            break

    terminal_at = ended_at or now
    close_active(terminal_at)
    close_pause(terminal_at)
    result.required_segments_completed = len(completed_required_indices)

    for interval in full_intervals:
        clipped = _clip_interval(interval, window_start, window_end)
        if clipped is None:
            continue
        result.intervals.append(clipped)
        seconds = clipped.seconds
        if clipped.category == "active_work":
            result.active_work_seconds += seconds
            if clipped.work_item_id is not None:
                result.work_item_active_seconds[clipped.work_item_id] = (
                    result.work_item_active_seconds.get(clipped.work_item_id, 0) + seconds
                )
            if interval.start >= window_start and interval.end <= window_end:
                result.uninterrupted_work_seconds.append(interval.seconds)
        elif clipped.category == "break":
            result.break_seconds += seconds
        elif clipped.category == "paused":
            result.paused_seconds += seconds
    return result
