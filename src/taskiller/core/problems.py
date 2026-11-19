from __future__ import annotations

from typing import Any

PROBLEM_CODES = frozenset(
    {
        "account_deletion_pending",
        "account_state_conflict",
        "admin_auth_required",
        "admin_challenge_invalid",
        "admin_credentials_invalid",
        "admin_csrf_failed",
        "admin_disabled",
        "admin_encryption_unavailable",
        "admin_invitation_invalid",
        "admin_last_owner",
        "admin_mfa_invalid",
        "admin_origin_forbidden",
        "admin_permission_denied",
        "admin_step_up_required",
        "admin_writes_disabled",
        "auth_origin_forbidden",
        "auth_session_not_found",
        "data_export_not_found",
        "email_already_registered",
        "email_delivery_unavailable",
        "empty_focus_plan",
        "focus_plan_source_conflict",
        "focus_plan_template_unexecutable",
        "focus_plan_work_item_mismatch",
        "historical_event_forbidden",
        "idempotency_conflict",
        "idempotency_key_reused",
        "idempotency_replay_missing",
        "import_type_invalid",
        "internal_error",
        "invalid_access_token",
        "invalid_credentials",
        "invalid_cursor",
        "invalid_date_range",
        "invalid_datetime_timezone",
        "invalid_focus_plan_link",
        "invalid_hierarchy",
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
        "job_not_retryable",
        "not_found",
        "open_session_exists",
        "portable_import_item_failed",
        "precondition_failed",
        "preferences_missing",
        "project_not_executable",
        "project_requires_next_action",
        "rate_limit_exceeded",
        "reason_required",
        "recommendation_context_incomplete",
        "recommendation_work_item_mismatch",
        "refresh_token_reuse",
        "roles_unavailable",
        "self_grant_forbidden",
        "session_review_before_terminal",
        "session_terminal",
        "staff_already_enrolled",
        "staff_identity_conflict",
        "staff_session_invalid",
        "system_work_type_immutable",
        "unknown_admin_action",
        "validation_error",
        "work_item_has_children",
        "work_item_not_executable",
        "work_item_not_found",
        "work_item_state_conflict",
        "work_item_terminal",
        "work_type_missing",
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
