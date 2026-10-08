from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from statistics import median
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from taskiller.analytics.derive import (
    DerivedInterval,
    DerivedSessionMetrics,
    EventRecord,
    derive_session_metrics,
)
from taskiller.analytics.schemas import (
    AnalyticsBucket,
    AnalyticsSummary,
    AnalyticsTimeseries,
    AnalyticsTimeseriesPoint,
    FocusPatternItem,
    FocusPatterns,
    TimeOfDayPatternItem,
    WorkItemAnalytics,
    WorkTypeAnalytics,
    WorkTypeAnalyticsList,
)
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.models import UserPreferences
from taskiller.execution.models import (
    ExecutionSessionModel,
    SessionEventModel,
    SessionReviewModel,
)
from taskiller.work.models import WorkItem, WorkType
from taskiller.work.schemas import WorkItemKind

_PERSONALIZATION_WINDOW_DAYS = 90
_MIN_PERSONALIZATION_SESSIONS = 5
_MIN_PERSONALIZATION_SESSIONS_NO_REVIEWS = 8
_MIN_PERSONALIZATION_INTERVAL_SECONDS = 5 * 60
_MIN_PERSONALIZED_BLOCK_SECONDS = 15 * 60
_MAX_PERSONALIZED_BLOCK_SECONDS = 90 * 60


@dataclass(frozen=True, slots=True)
class PersonalFocusSignal:
    target_seconds: int
    sample_size: int
    median_focus_score: float | None
    work_type_slug: str


@dataclass(frozen=True, slots=True)
class WorkContextEntry:
    id: UUID
    kind: str
    ancestor_ids: tuple[UUID, ...]
    work_type_id: UUID | None
    work_type_slug: str | None
    estimated_effort_seconds: int | None
    planned_start_at: datetime | None


@dataclass(slots=True)
class LoadedHistory:
    sessions: list[ExecutionSessionModel]
    events: dict[UUID, list[EventRecord]]
    reviews: dict[UUID, SessionReviewModel]
    work_items: dict[UUID, WorkItem]
    work_types: dict[UUID, WorkType]
    preferences: UserPreferences


class AnalyticsService:
    def __init__(self, db: AsyncSession, *, owner_id: UUID) -> None:
        self.db = db
        self.owner_id = owner_id

    async def summary(self, from_at: datetime, to_at: datetime) -> AnalyticsSummary:
        start, end = self._validate_range(from_at, to_at)
        history = await self._load_history(end)
        ranged, full = self._derive_history(history, start, end)

        active = sum(item.active_work_seconds for item in ranged.values())
        breaks = sum(item.break_seconds for item in ranged.values())
        paused = sum(item.paused_seconds for item in ranged.values())
        completed = sum(
            1
            for session in history.sessions
            if session.state == "completed"
            and session.ended_at is not None
            and start <= session.ended_at < end
        )
        abandoned = sum(
            1
            for session in history.sessions
            if session.state == "abandoned"
            and session.ended_at is not None
            and start <= session.ended_at < end
        )
        completion_map = self._completion_map(full, start, end)
        estimate_errors = self._estimate_errors(history, full, completion_map)
        start_delays = self._start_delays(history, full, start, end)
        uninterrupted = [
            seconds
            for item in ranged.values()
            for seconds in item.uninterrupted_work_seconds
            if seconds > 0
        ]
        planned, completed_segments = self._adherence_counts(history, ranged, start, end)
        return AnalyticsSummary.model_validate(
            {
                "from": start,
                "to": end,
                "activeWorkSeconds": active,
                "breakSeconds": breaks,
                "pausedSeconds": paused,
                "sessionsCompleted": completed,
                "sessionsAbandoned": abandoned,
                "choresCompleted": len(completion_map),
                "medianUninterruptedWorkSeconds": self._median_int(uninterrupted),
                "medianEstimateErrorSeconds": self._median_int(list(estimate_errors.values())),
                "medianStartDelaySeconds": self._median_int(start_delays),
                "requiredSegmentsCompleted": completed_segments,
                "requiredSegmentsPlanned": planned,
                "planAdherenceRate": self._ratio(completed_segments, planned),
            }
        )

    async def work_types(self, from_at: datetime, to_at: datetime) -> WorkTypeAnalyticsList:
        start, end = self._validate_range(from_at, to_at)
        history = await self._load_history(end)
        ranged, full = self._derive_history(history, start, end)
        completion_map = self._completion_map(full, start, end)
        estimate_errors = self._estimate_errors(history, full, completion_map)

        active_by_key: dict[tuple[UUID | None, str | None], int] = {}
        sessions_by_key: dict[tuple[UUID | None, str | None], set[UUID]] = {}
        intervals_by_key: dict[tuple[UUID | None, str | None], list[int]] = {}
        terminal_by_key: dict[tuple[UUID | None, str | None], set[UUID]] = {}
        completed_by_key: dict[tuple[UUID | None, str | None], set[UUID]] = {}
        focus_by_key: dict[tuple[UUID | None, str | None], list[int]] = {}
        estimate_by_key: dict[tuple[UUID | None, str | None], list[int]] = {}

        for session in history.sessions:
            metrics = ranged.get(session.id)
            if metrics is None:
                continue
            touched: set[tuple[UUID | None, str | None]] = set()
            for interval in metrics.intervals:
                if interval.category != "active_work" or interval.work_item_id is None:
                    continue
                context = self._context_for(session, interval.work_item_id, history)
                key = (context.work_type_id, context.work_type_slug)
                active_by_key[key] = active_by_key.get(key, 0) + interval.seconds
                sessions_by_key.setdefault(key, set()).add(session.id)
                touched.add(key)
            full_metrics = full.get(session.id)
            if full_metrics is not None:
                for interval in full_metrics.intervals:
                    if (
                        interval.category != "active_work"
                        or interval.work_item_id is None
                        or interval.start < start
                        or interval.end > end
                    ):
                        continue
                    context = self._context_for(session, interval.work_item_id, history)
                    key = (context.work_type_id, context.work_type_slug)
                    intervals_by_key.setdefault(key, []).append(interval.seconds)
            if (
                session.ended_at is not None
                and start <= session.ended_at < end
                and session.state in {"completed", "abandoned"}
            ):
                for key in touched:
                    terminal_by_key.setdefault(key, set()).add(session.id)
                    if session.state == "completed":
                        completed_by_key.setdefault(key, set()).add(session.id)
                    review = history.reviews.get(session.id)
                    if review is not None and review.focus_score is not None:
                        focus_by_key.setdefault(key, []).append(review.focus_score)

        for work_item_id, error in estimate_errors.items():
            context = self._best_context_for_item(history, work_item_id, end)
            if context is None:
                continue
            key = (context.work_type_id, context.work_type_slug)
            estimate_by_key.setdefault(key, []).append(error)

        keys = set(active_by_key) | set(terminal_by_key) | set(estimate_by_key)
        items = []
        for key in sorted(keys, key=lambda item: (item[1] or "", str(item[0] or ""))):
            terminal_count = len(terminal_by_key.get(key, set()))
            items.append(
                WorkTypeAnalytics(
                    work_type_id=key[0],
                    work_type_slug=key[1],
                    active_work_seconds=active_by_key.get(key, 0),
                    session_count=len(sessions_by_key.get(key, set())),
                    median_uninterrupted_work_seconds=self._median_int(
                        intervals_by_key.get(key, [])
                    ),
                    median_estimate_error_seconds=self._median_int(estimate_by_key.get(key, [])),
                    completion_rate=(
                        len(completed_by_key.get(key, set())) / terminal_count
                        if terminal_count
                        else None
                    ),
                    median_focus_score=self._median_float(focus_by_key.get(key, [])),
                )
            )
        return WorkTypeAnalyticsList(items=items)

    async def work_item(
        self, work_item_id: UUID, from_at: datetime, to_at: datetime
    ) -> WorkItemAnalytics:
        start, end = self._validate_range(from_at, to_at)
        history = await self._load_history(end)
        work_item = history.work_items.get(work_item_id)
        if work_item is None:
            raise ApiError(404, "work_item_not_found", "Work item not found")
        ranged, full = self._derive_history(history, start, end)
        completion_map = self._completion_map(full, start, end)
        estimate_errors = self._estimate_errors(history, full, completion_map)

        active = 0
        breaks = 0
        paused = 0
        session_ids: set[UUID] = set()
        planned = 0
        completed_segments = 0
        first_started: datetime | None = None

        for session in history.sessions:
            metrics = ranged.get(session.id)
            full_metrics = full.get(session.id)
            if metrics is None or full_metrics is None:
                continue
            target_context = self._target_context(session, history)
            target_in_scope = self._context_in_scope(target_context, work_item_id)
            active_in_scope = False
            for interval in metrics.intervals:
                if interval.category != "active_work" or interval.work_item_id is None:
                    continue
                context = self._context_for(session, interval.work_item_id, history)
                if self._context_in_scope(context, work_item_id):
                    active += interval.seconds
                    active_in_scope = True
            if target_in_scope:
                breaks += metrics.break_seconds
                paused += metrics.paused_seconds
                if (
                    session.ended_at is not None
                    and start <= session.ended_at < end
                    and session.state in {"completed", "abandoned"}
                ):
                    planned += metrics.required_segments_planned
                    completed_segments += metrics.required_segments_completed
            if target_in_scope or active_in_scope:
                session_ids.add(session.id)

            for interval in full_metrics.intervals:
                if interval.category != "active_work" or interval.work_item_id is None:
                    continue
                context = self._context_for(session, interval.work_item_id, history)
                if self._context_in_scope(context, work_item_id) and (
                    first_started is None or interval.start < first_started
                ):
                    first_started = interval.start

        scoped_errors = []
        for completed_id, error in estimate_errors.items():
            context = self._best_context_for_item(history, completed_id, end)
            if context is not None and self._context_in_scope(context, work_item_id):
                scoped_errors.append(error)

        return WorkItemAnalytics(
            work_item_id=work_item_id,
            active_work_seconds=active,
            break_seconds=breaks,
            paused_seconds=paused,
            session_count=len(session_ids),
            estimate_error_seconds=sum(scoped_errors) if scoped_errors else None,
            required_segments_completed=completed_segments,
            required_segments_planned=planned,
            plan_adherence_rate=self._ratio(completed_segments, planned),
            first_started_at=first_started,
            completed_at=work_item.completed_at,
        )

    async def timeseries(
        self,
        from_at: datetime,
        to_at: datetime,
        bucket: AnalyticsBucket,
    ) -> AnalyticsTimeseries:
        start, end = self._validate_range(from_at, to_at)
        history = await self._load_history(end)
        ranged, full = self._derive_history(history, start, end)
        zone = ZoneInfo(history.preferences.timezone)
        week_start = history.preferences.week_starts_on
        points = self._empty_buckets(start, end, bucket, zone, week_start)

        def point_for(at: datetime) -> dict[str, int]:
            key = self._bucket_start(at, bucket, zone, week_start)
            return points.setdefault(
                key,
                {
                    "active": 0,
                    "break": 0,
                    "paused": 0,
                    "sessions": 0,
                    "chores": 0,
                },
            )

        for metrics in ranged.values():
            for interval in metrics.intervals:
                for part_start, part_end in self._split_by_bucket(
                    interval, bucket, zone, week_start
                ):
                    seconds = max(0, round((part_end - part_start).total_seconds()))
                    values = point_for(part_start)
                    if interval.category == "active_work":
                        values["active"] += seconds
                    elif interval.category == "break":
                        values["break"] += seconds
                    elif interval.category == "paused":
                        values["paused"] += seconds

        for session in history.sessions:
            if (
                session.state == "completed"
                and session.ended_at is not None
                and start <= session.ended_at < end
            ):
                point_for(session.ended_at)["sessions"] += 1
        for _, completed_at in self._completion_map(full, start, end).values():
            point_for(completed_at)["chores"] += 1

        response_points = [
            AnalyticsTimeseriesPoint(
                bucket_start=bucket_start,
                active_work_seconds=values["active"],
                break_seconds=values["break"],
                paused_seconds=values["paused"],
                sessions_completed=values["sessions"],
                chores_completed=values["chores"],
            )
            for bucket_start, values in sorted(points.items())
            if bucket_start < end.astimezone(zone)
        ]
        return AnalyticsTimeseries.model_validate(
            {
                "from": start,
                "to": end,
                "bucket": bucket,
                "timezone": history.preferences.timezone,
                "points": response_points,
            }
        )

    async def focus_patterns(self, from_at: datetime, to_at: datetime) -> FocusPatterns:
        start, end = self._validate_range(from_at, to_at)
        history = await self._load_history(end)
        ranged, full = self._derive_history(history, start, end)
        zone = ZoneInfo(history.preferences.timezone)

        durations: dict[tuple[UUID | None, str], list[int]] = {}
        sessions_by_key: dict[tuple[UUID | None, str], set[UUID]] = {}
        focus_by_key: dict[tuple[UUID | None, str], list[int]] = {}
        hour_active = {hour: 0 for hour in range(24)}
        hour_sessions: dict[int, set[UUID]] = {hour: set() for hour in range(24)}
        hour_focus: dict[int, list[int]] = {hour: [] for hour in range(24)}

        for session in history.sessions:
            if (
                session.state != "completed"
                or session.ended_at is None
                or not (start <= session.ended_at < end)
            ):
                continue
            metrics = ranged.get(session.id)
            if metrics is None:
                continue
            touched: set[tuple[UUID | None, str]] = set()
            touched_hours: set[int] = set()
            for interval in metrics.intervals:
                if interval.category != "active_work" or interval.work_item_id is None:
                    continue
                context = self._context_for(session, interval.work_item_id, history)
                slug = context.work_type_slug or "uncategorized"
                key = (context.work_type_id, slug)
                touched.add(key)
                for part_start, part_end in self._split_by_hour(interval, zone):
                    hour = part_start.astimezone(zone).hour
                    hour_active[hour] += max(0, round((part_end - part_start).total_seconds()))
                    hour_sessions[hour].add(session.id)
                    touched_hours.add(hour)
            full_metrics = full.get(session.id)
            if full_metrics is not None:
                for interval in full_metrics.intervals:
                    if (
                        interval.category != "active_work"
                        or interval.work_item_id is None
                        or interval.start < start
                        or interval.end > end
                        or interval.seconds < _MIN_PERSONALIZATION_INTERVAL_SECONDS
                    ):
                        continue
                    context = self._context_for(session, interval.work_item_id, history)
                    slug = context.work_type_slug or "uncategorized"
                    durations.setdefault((context.work_type_id, slug), []).append(interval.seconds)
            review = history.reviews.get(session.id)
            for key in touched:
                sessions_by_key.setdefault(key, set()).add(session.id)
                if review is not None and review.focus_score is not None:
                    focus_by_key.setdefault(key, []).append(review.focus_score)
            if review is not None and review.focus_score is not None:
                for hour in touched_hours:
                    hour_focus[hour].append(review.focus_score)

        items = []
        for key in sorted(sessions_by_key, key=lambda item: (item[1], str(item[0] or ""))):
            values = durations.get(key, [])
            scores = focus_by_key.get(key, [])
            sample_size = len(sessions_by_key[key])
            median_focus = self._median_float(scores)
            eligible = self._personalization_eligible(
                sample_size=sample_size,
                interval_count=len(values),
                median_focus_score=median_focus,
                focus_review_count=len(scores),
            )
            items.append(
                FocusPatternItem(
                    work_type_id=key[0],
                    work_type_slug=key[1],
                    sample_size=sample_size,
                    median_uninterrupted_work_seconds=self._median_int(values),
                    p25_uninterrupted_work_seconds=self._percentile_int(values, 0.25),
                    p75_uninterrupted_work_seconds=self._percentile_int(values, 0.75),
                    median_focus_score=median_focus,
                    recommendation_personalization_eligible=eligible,
                )
            )
        time_of_day = [
            TimeOfDayPatternItem(
                hour_start=hour,
                active_work_seconds=hour_active[hour],
                session_count=len(hour_sessions[hour]),
                median_focus_score=self._median_float(hour_focus[hour]),
            )
            for hour in range(24)
        ]
        return FocusPatterns.model_validate(
            {
                "from": start,
                "to": end,
                "timezone": history.preferences.timezone,
                "items": items,
                "timeOfDay": time_of_day,
            }
        )

    async def personalization_signal(
        self,
        *,
        work_type_id: UUID,
        work_type_slug: str,
        now: datetime | None = None,
    ) -> PersonalFocusSignal | None:
        end = (now or utc_now()).astimezone(UTC)
        start = end - timedelta(days=_PERSONALIZATION_WINDOW_DAYS)
        patterns = await self.focus_patterns(start, end)
        pattern = next(
            (
                item
                for item in patterns.items
                if item.work_type_id == work_type_id and item.work_type_slug == work_type_slug
            ),
            None,
        )
        if (
            pattern is None
            or not pattern.recommendation_personalization_eligible
            or pattern.median_uninterrupted_work_seconds is None
        ):
            return None
        target = self._round_to_five_minutes(pattern.median_uninterrupted_work_seconds)
        target = max(
            _MIN_PERSONALIZED_BLOCK_SECONDS,
            min(_MAX_PERSONALIZED_BLOCK_SECONDS, target),
        )
        return PersonalFocusSignal(
            target_seconds=target,
            sample_size=pattern.sample_size,
            median_focus_score=pattern.median_focus_score,
            work_type_slug=pattern.work_type_slug,
        )

    async def _load_history(self, to_at: datetime) -> LoadedHistory:
        sessions = list(
            (
                await self.db.scalars(
                    select(ExecutionSessionModel)
                    .where(
                        ExecutionSessionModel.owner_id == self.owner_id,
                        ExecutionSessionModel.session_started_at < to_at,
                    )
                    .order_by(ExecutionSessionModel.session_started_at, ExecutionSessionModel.id)
                )
            ).all()
        )
        session_ids = [row.id for row in sessions]
        events: dict[UUID, list[EventRecord]] = {session_id: [] for session_id in session_ids}
        reviews: dict[UUID, SessionReviewModel] = {}
        if session_ids:
            event_rows = list(
                (
                    await self.db.scalars(
                        select(SessionEventModel)
                        .where(SessionEventModel.session_id.in_(session_ids))
                        .order_by(
                            SessionEventModel.session_id,
                            SessionEventModel.occurred_at,
                            SessionEventModel.id,
                        )
                    )
                ).all()
            )
            for row in event_rows:
                events[row.session_id].append(
                    EventRecord(
                        type=row.type,
                        occurred_at=row.occurred_at,
                        segment_index=row.segment_index,
                        payload=dict(row.payload_json),
                    )
                )
            review_rows = list(
                (
                    await self.db.scalars(
                        select(SessionReviewModel).where(
                            SessionReviewModel.session_id.in_(session_ids)
                        )
                    )
                ).all()
            )
            reviews = {row.session_id: row for row in review_rows}

        work_item_rows = list(
            (
                await self.db.scalars(select(WorkItem).where(WorkItem.owner_id == self.owner_id))
            ).all()
        )
        work_items = {row.id: row for row in work_item_rows}
        work_type_rows = list(
            (
                await self.db.scalars(
                    select(WorkType).where(
                        or_(WorkType.owner_id == self.owner_id, WorkType.owner_id.is_(None))
                    )
                )
            ).all()
        )
        work_types = {row.id: row for row in work_type_rows}
        preferences = await self.db.get(UserPreferences, self.owner_id)
        if preferences is None:
            raise ApiError(500, "preferences_missing", "User preferences are missing")
        return LoadedHistory(
            sessions=sessions,
            events=events,
            reviews=reviews,
            work_items=work_items,
            work_types=work_types,
            preferences=preferences,
        )

    def _derive_history(
        self,
        history: LoadedHistory,
        start: datetime,
        end: datetime,
    ) -> tuple[dict[UUID, DerivedSessionMetrics], dict[UUID, DerivedSessionMetrics]]:
        now = utc_now()
        ranged: dict[UUID, DerivedSessionMetrics] = {}
        full: dict[UUID, DerivedSessionMetrics] = {}
        for session in history.sessions:
            session_end = session.ended_at or now
            full_end = min(end, session_end)
            if full_end > session.session_started_at:
                full[session.id] = derive_session_metrics(
                    session_id=session.id,
                    session_work_item_id=session.work_item_id,
                    plan_snapshot=dict(session.plan_snapshot_json),
                    events=history.events.get(session.id, []),
                    session_started_at=session.session_started_at,
                    ended_at=session.ended_at,
                    now=now,
                    window_start=session.session_started_at,
                    window_end=full_end,
                )
            overlap_start = max(start, session.session_started_at)
            overlap_end = min(end, session_end)
            if overlap_end > overlap_start:
                ranged[session.id] = derive_session_metrics(
                    session_id=session.id,
                    session_work_item_id=session.work_item_id,
                    plan_snapshot=dict(session.plan_snapshot_json),
                    events=history.events.get(session.id, []),
                    session_started_at=session.session_started_at,
                    ended_at=session.ended_at,
                    now=now,
                    window_start=overlap_start,
                    window_end=overlap_end,
                )
        return ranged, full

    def _target_context(
        self, session: ExecutionSessionModel, history: LoadedHistory
    ) -> WorkContextEntry:
        return self._context_for(session, session.work_item_id, history)

    def _context_for(
        self,
        session: ExecutionSessionModel,
        work_item_id: UUID,
        history: LoadedHistory,
    ) -> WorkContextEntry:
        snapshot = dict(session.work_context_snapshot_json or {})
        target = snapshot.get("target")
        if isinstance(target, dict) and str(target.get("id")) == str(work_item_id):
            return self._parse_context(target)
        linked = snapshot.get("linkedWorkItems")
        if isinstance(linked, dict):
            value = linked.get(str(work_item_id))
            if isinstance(value, dict):
                return self._parse_context(value)
        current = history.work_items.get(work_item_id)
        if current is None:
            return WorkContextEntry(
                id=work_item_id,
                kind="chore",
                ancestor_ids=(),
                work_type_id=None,
                work_type_slug=None,
                estimated_effort_seconds=None,
                planned_start_at=None,
            )
        ancestors = self._current_ancestors(current, history.work_items)
        work_type = (
            history.work_types.get(current.work_type_id)
            if current.work_type_id is not None
            else None
        )
        return WorkContextEntry(
            id=current.id,
            kind=current.kind,
            ancestor_ids=ancestors,
            work_type_id=current.work_type_id,
            work_type_slug=work_type.slug if work_type is not None else None,
            estimated_effort_seconds=current.estimated_effort_seconds,
            planned_start_at=current.planned_start_at,
        )

    @staticmethod
    def _parse_context(value: dict[str, Any]) -> WorkContextEntry:
        raw_ancestors = value.get("ancestorIds")
        ancestors = (
            tuple(UUID(str(item)) for item in raw_ancestors if item is not None)
            if isinstance(raw_ancestors, list)
            else ()
        )
        planned = value.get("plannedStartAt")
        planned_at = datetime.fromisoformat(str(planned)) if planned is not None else None
        if planned_at is not None and planned_at.tzinfo is None:
            planned_at = planned_at.replace(tzinfo=UTC)
        raw_work_type = value.get("workTypeId")
        return WorkContextEntry(
            id=UUID(str(value["id"])),
            kind=str(value.get("kind", "chore")),
            ancestor_ids=ancestors,
            work_type_id=UUID(str(raw_work_type)) if raw_work_type is not None else None,
            work_type_slug=(
                str(value["workTypeSlug"]) if value.get("workTypeSlug") is not None else None
            ),
            estimated_effort_seconds=(
                int(value["estimatedEffortSeconds"])
                if value.get("estimatedEffortSeconds") is not None
                else None
            ),
            planned_start_at=planned_at,
        )

    @staticmethod
    def _current_ancestors(row: WorkItem, work_items: dict[UUID, WorkItem]) -> tuple[UUID, ...]:
        result: list[UUID] = []
        seen: set[UUID] = set()
        parent_id = row.parent_id
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            result.append(parent_id)
            parent = work_items.get(parent_id)
            if parent is None:
                break
            parent_id = parent.parent_id
        return tuple(result)

    @staticmethod
    def _context_in_scope(context: WorkContextEntry, root_id: UUID) -> bool:
        return context.id == root_id or root_id in context.ancestor_ids

    def _completion_map(
        self,
        full: dict[UUID, DerivedSessionMetrics],
        start: datetime,
        end: datetime,
    ) -> dict[UUID, tuple[UUID, datetime]]:
        completed: dict[UUID, tuple[UUID, datetime]] = {}
        for session_id, metrics in full.items():
            for work_item_id, at in metrics.completed_work_items:
                if start <= at < end:
                    previous = completed.get(work_item_id)
                    if previous is None or at < previous[1]:
                        completed[work_item_id] = (session_id, at)
        return completed

    def _estimate_errors(
        self,
        history: LoadedHistory,
        full: dict[UUID, DerivedSessionMetrics],
        completed: dict[UUID, tuple[UUID, datetime]],
    ) -> dict[UUID, int]:
        result: dict[UUID, int] = {}
        for work_item_id, (completion_session_id, completed_at) in completed.items():
            session = next(
                (row for row in history.sessions if row.id == completion_session_id),
                None,
            )
            if session is None:
                continue
            context = self._context_for(session, work_item_id, history)
            if context.kind != WorkItemKind.CHORE.value or context.estimated_effort_seconds is None:
                continue
            actual = 0
            for metrics in full.values():
                for interval in metrics.intervals:
                    if (
                        interval.category != "active_work"
                        or interval.work_item_id != work_item_id
                        or interval.start >= completed_at
                    ):
                        continue
                    interval_end = min(interval.end, completed_at)
                    actual += max(0, round((interval_end - interval.start).total_seconds()))
            result[work_item_id] = actual - context.estimated_effort_seconds
        return result

    def _start_delays(
        self,
        history: LoadedHistory,
        full: dict[UUID, DerivedSessionMetrics],
        start: datetime,
        end: datetime,
    ) -> list[int]:
        firsts: dict[UUID, tuple[datetime, WorkContextEntry]] = {}
        session_by_id = {row.id: row for row in history.sessions}
        for session_id, metrics in full.items():
            session = session_by_id[session_id]
            for interval in metrics.intervals:
                if interval.category != "active_work" or interval.work_item_id is None:
                    continue
                context = self._context_for(session, interval.work_item_id, history)
                previous = firsts.get(context.id)
                if previous is None or interval.start < previous[0]:
                    firsts[context.id] = (interval.start, context)
        delays = []
        for first_at, context in firsts.values():
            if not (start <= first_at < end) or context.planned_start_at is None:
                continue
            delays.append(max(0, round((first_at - context.planned_start_at).total_seconds())))
        return delays

    @staticmethod
    def _adherence_counts(
        history: LoadedHistory,
        ranged: dict[UUID, DerivedSessionMetrics],
        start: datetime,
        end: datetime,
    ) -> tuple[int, int]:
        planned = 0
        completed = 0
        for session in history.sessions:
            if (
                session.ended_at is None
                or not (start <= session.ended_at < end)
                or session.state not in {"completed", "abandoned"}
            ):
                continue
            metrics = ranged.get(session.id)
            if metrics is None:
                continue
            planned += metrics.required_segments_planned
            completed += metrics.required_segments_completed
        return planned, completed

    def _best_context_for_item(
        self, history: LoadedHistory, work_item_id: UUID, before: datetime
    ) -> WorkContextEntry | None:
        candidates = [
            session for session in history.sessions if session.session_started_at < before
        ]
        for session in reversed(candidates):
            snapshot = dict(session.work_context_snapshot_json or {})
            target = snapshot.get("target")
            linked = snapshot.get("linkedWorkItems")
            if isinstance(target, dict) and str(target.get("id")) == str(work_item_id):
                return self._parse_context(target)
            if isinstance(linked, dict) and isinstance(linked.get(str(work_item_id)), dict):
                return self._parse_context(linked[str(work_item_id)])
        current = history.work_items.get(work_item_id)
        if current is None:
            return None
        work_type = (
            history.work_types.get(current.work_type_id)
            if current.work_type_id is not None
            else None
        )
        return WorkContextEntry(
            id=current.id,
            kind=current.kind,
            ancestor_ids=self._current_ancestors(current, history.work_items),
            work_type_id=current.work_type_id,
            work_type_slug=work_type.slug if work_type is not None else None,
            estimated_effort_seconds=current.estimated_effort_seconds,
            planned_start_at=current.planned_start_at,
        )

    @staticmethod
    def _validate_range(from_at: datetime, to_at: datetime) -> tuple[datetime, datetime]:
        for name, value in (("from", from_at), ("to", to_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ApiError(
                    422,
                    "invalid_datetime_timezone",
                    "Datetime must include a UTC offset",
                    f"{name} must include a UTC offset.",
                )
        start = from_at.astimezone(UTC)
        end = to_at.astimezone(UTC)
        if start >= end:
            raise ApiError(
                422, "invalid_time_range", "Invalid time range", "from must be before to."
            )
        return start, end

    @staticmethod
    def _median_int(values: list[int]) -> int | None:
        return round(median(values)) if values else None

    @staticmethod
    def _median_float(values: list[int]) -> float | None:
        return float(median(values)) if values else None

    @staticmethod
    def _percentile_int(values: list[int], percentile: float) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * percentile
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    @staticmethod
    def _personalization_eligible(
        *,
        sample_size: int,
        interval_count: int,
        median_focus_score: float | None,
        focus_review_count: int,
    ) -> bool:
        if interval_count < _MIN_PERSONALIZATION_SESSIONS:
            return False
        if focus_review_count >= 3:
            return (
                sample_size >= _MIN_PERSONALIZATION_SESSIONS
                and median_focus_score is not None
                and median_focus_score >= 3
            )
        return sample_size >= _MIN_PERSONALIZATION_SESSIONS_NO_REVIEWS

    @staticmethod
    def _round_to_five_minutes(seconds: int) -> int:
        quantum = 5 * 60
        return max(quantum, round(seconds / quantum) * quantum)

    @staticmethod
    def _bucket_start(
        at: datetime,
        bucket: AnalyticsBucket,
        zone: ZoneInfo,
        week_starts_on: int,
    ) -> datetime:
        local = at.astimezone(zone)
        day = local.date()
        if bucket is AnalyticsBucket.WEEK:
            python_weekday = (week_starts_on - 1) % 7
            day -= timedelta(days=(day.weekday() - python_weekday) % 7)
        return datetime.combine(day, time.min, tzinfo=zone)

    def _empty_buckets(
        self,
        start: datetime,
        end: datetime,
        bucket: AnalyticsBucket,
        zone: ZoneInfo,
        week_starts_on: int,
    ) -> dict[datetime, dict[str, int]]:
        first = self._bucket_start(start, bucket, zone, week_starts_on)
        result: dict[datetime, dict[str, int]] = {}
        current = first
        step = timedelta(days=1 if bucket is AnalyticsBucket.DAY else 7)
        while current < end.astimezone(zone):
            result[current] = {
                "active": 0,
                "break": 0,
                "paused": 0,
                "sessions": 0,
                "chores": 0,
            }
            current += step
        return result

    def _split_by_bucket(
        self,
        interval: DerivedInterval,
        bucket: AnalyticsBucket,
        zone: ZoneInfo,
        week_starts_on: int,
    ) -> list[tuple[datetime, datetime]]:
        parts: list[tuple[datetime, datetime]] = []
        cursor = interval.start
        step = timedelta(days=1 if bucket is AnalyticsBucket.DAY else 7)
        while cursor < interval.end:
            local_bucket = self._bucket_start(cursor, bucket, zone, week_starts_on)
            next_boundary = (local_bucket + step).astimezone(UTC)
            part_end = min(interval.end, next_boundary)
            parts.append((cursor, part_end))
            if part_end <= cursor:
                break
            cursor = part_end
        return parts

    @staticmethod
    def _split_by_hour(
        interval: DerivedInterval, zone: ZoneInfo
    ) -> list[tuple[datetime, datetime]]:
        parts: list[tuple[datetime, datetime]] = []
        cursor = interval.start
        while cursor < interval.end:
            local = cursor.astimezone(zone)
            hour_start = local.replace(minute=0, second=0, microsecond=0)
            next_hour = (hour_start + timedelta(hours=1)).astimezone(UTC)
            part_end = min(interval.end, next_hour)
            parts.append((cursor, part_end))
            if part_end <= cursor:
                break
            cursor = part_end
        return parts
