from datetime import UTC, datetime, timedelta
from uuid import uuid4

from taskiller.analytics.derive import EventRecord, derive_session_metrics


def _at(minutes: int, seconds: int = 0) -> datetime:
    return datetime(2026, 9, 28, 10, minutes, seconds, tzinfo=UTC)


def test_derives_work_break_pause_and_linked_work_item_time() -> None:
    session_id = uuid4()
    sprint_id = uuid4()
    chore_id = uuid4()
    plan = {
        "segments": [
            {
                "kind": "work",
                "targetSeconds": 1800,
                "linkedWorkItemId": str(chore_id),
                "optional": False,
            },
            {
                "kind": "break",
                "targetSeconds": 300,
                "optional": True,
            },
        ]
    }
    events = [
        EventRecord("session_started", _at(0), None, {}),
        EventRecord("segment_started", _at(0), 0, {}),
        EventRecord("paused", _at(10), None, {}),
        EventRecord("resumed", _at(12), None, {}),
        EventRecord("segment_completed", _at(22), 0, {}),
        EventRecord("break_started", _at(23), 1, {}),
        EventRecord("break_ended", _at(28), 1, {}),
        EventRecord("session_completed", _at(29), None, {}),
    ]
    metrics = derive_session_metrics(
        session_id=session_id,
        session_work_item_id=sprint_id,
        plan_snapshot=plan,
        events=events,
        session_started_at=_at(0),
        ended_at=_at(29),
        now=_at(29),
        window_start=_at(0),
        window_end=_at(30),
    )

    assert metrics.active_work_seconds == 20 * 60
    assert metrics.break_seconds == 5 * 60
    assert metrics.paused_seconds == 2 * 60
    assert metrics.work_item_active_seconds == {chore_id: 20 * 60}
    assert metrics.uninterrupted_work_seconds == [10 * 60, 10 * 60]
    assert metrics.required_segments_planned == 1
    assert metrics.required_segments_completed == 1


def test_window_clips_totals_but_not_full_uninterrupted_sample() -> None:
    session_id = uuid4()
    chore_id = uuid4()
    events = [
        EventRecord("session_started", _at(0), None, {}),
        EventRecord("segment_started", _at(0), 0, {}),
        EventRecord("segment_completed", _at(20), 0, {}),
        EventRecord("session_completed", _at(20), None, {}),
    ]
    metrics = derive_session_metrics(
        session_id=session_id,
        session_work_item_id=chore_id,
        plan_snapshot={"segments": [{"kind": "work", "targetSeconds": 1200, "optional": False}]},
        events=events,
        session_started_at=_at(0),
        ended_at=_at(20),
        now=_at(20),
        window_start=_at(5),
        window_end=_at(15),
    )

    assert metrics.active_work_seconds == 10 * 60
    assert metrics.uninterrupted_work_seconds == []


def test_completion_without_payload_uses_current_linked_work_item() -> None:
    session_id = uuid4()
    sprint_id = uuid4()
    chore_id = uuid4()
    completed_at = _at(15)
    metrics = derive_session_metrics(
        session_id=session_id,
        session_work_item_id=sprint_id,
        plan_snapshot={
            "segments": [
                {
                    "kind": "work",
                    "targetSeconds": 1200,
                    "linkedWorkItemId": str(chore_id),
                    "optional": False,
                }
            ]
        },
        events=[
            EventRecord("session_started", _at(0), None, {}),
            EventRecord("segment_started", _at(0), 0, {}),
            EventRecord("work_item_completed", completed_at, None, {}),
            EventRecord("session_completed", _at(16), None, {}),
        ],
        session_started_at=_at(0),
        ended_at=_at(16),
        now=_at(16),
        window_start=_at(0),
        window_end=_at(20),
    )

    assert metrics.completed_work_items == [(chore_id, completed_at)]
    assert metrics.active_work_seconds == 16 * 60


def test_open_session_is_derived_only_until_now() -> None:
    session_id = uuid4()
    chore_id = uuid4()
    start = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    now = start + timedelta(minutes=7)
    metrics = derive_session_metrics(
        session_id=session_id,
        session_work_item_id=chore_id,
        plan_snapshot={"segments": [{"kind": "work", "targetSeconds": 1800, "optional": False}]},
        events=[
            EventRecord("session_started", start, None, {}),
            EventRecord("segment_started", start, 0, {}),
        ],
        session_started_at=start,
        ended_at=None,
        now=now,
        window_start=start,
        window_end=start + timedelta(hours=1),
    )

    assert metrics.active_work_seconds == 7 * 60
