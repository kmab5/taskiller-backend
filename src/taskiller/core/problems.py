from __future__ import annotations

from typing import Any

PROBLEM_CODES = frozenset(
    {
        "auth_session_not_found",
        "data_export_not_found",
        "email_already_registered",
        "email_delivery_unavailable",
        "empty_focus_plan",
        "focus_plan_source_conflict",
        "focus_plan_template_unexecutable",
        "focus_plan_work_item_mismatch",
        "idempotency_key_reused",
        "idempotency_replay_missing",
        "internal_error",
        "invalid_access_token",
        "invalid_credentials",
        "invalid_cursor",
        "invalid_date_range",
        "invalid_datetime_timezone",
        "invalid_focus_plan_link",
        "invalid_preferred_work_block_range",
        "invalid_project_target",
        "invalid_refresh_token",
        "invalid_reorder_anchor",
        "invalid_session_event",
        "invalid_session_transition",
        "invalid_time_range",
        "invalid_timezone",
        "invalid_work_hierarchy",
        "invalid_work_type",
        "open_session_exists",
        "precondition_failed",
        "preferences_missing",
        "project_not_executable",
        "project_requires_next_action",
        "rate_limit_exceeded",
        "recommendation_context_incomplete",
        "recommendation_work_item_mismatch",
        "refresh_token_reuse",
        "session_review_before_terminal",
        "session_terminal",
        "system_work_type_immutable",
        "validation_error",
        "work_item_has_children",
        "work_item_not_executable",
        "work_item_not_found",
        "work_item_state_conflict",
        "work_item_terminal",
        "work_type_not_found",
        "work_type_slug_conflict",
    }
)


class ApiError(Exception):
    """Framework-neutral compatibility error retained for shared domain helpers."""

    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        detail: str | None = None,
        *,
        meta: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.meta = meta
        self.headers = headers or {}
