import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from taskiller.core.config import Settings

logger = logging.getLogger(__name__)


PROBLEM_CODES = frozenset(
    {
        "auth_session_not_found",
        "data_export_not_found",
        "email_already_registered",
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


def problem_response(request: Request, error: ApiError) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"/problems/{error.code}",
        "title": error.title,
        "status": error.status_code,
        "code": error.code,
        "instance": request.url.path,
    }
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["requestId"] = request_id
    if error.detail:
        body["detail"] = error.detail
    if error.meta:
        body["meta"] = error.meta
    headers = dict(error.headers)
    if request_id:
        headers.setdefault("X-Request-ID", request_id)
    headers.setdefault("Cache-Control", "no-store")
    settings = cast(Settings | None, getattr(request.app.state, "settings", None))
    if settings is not None and settings.security_headers_enabled:
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.is_production and settings.hsts_max_age_seconds:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.hsts_max_age_seconds}; includeSubDomains",
            )
    return JSONResponse(
        status_code=error.status_code,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = ApiError(
            422,
            "validation_error",
            "Request validation failed",
            "One or more request values are invalid.",
            meta={
                "errors": [
                    {
                        "type": item.get("type"),
                        "loc": item.get("loc"),
                        "msg": item.get("msg"),
                    }
                    for item in exc.errors()
                ]
            },
        )
        return problem_response(request, error)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception(
            "unhandled_request_error",
            extra={"request_id": request_id, "path": request.url.path},
        )
        return problem_response(
            request,
            ApiError(
                500,
                "internal_error",
                "Internal server error",
                "The request could not be completed.",
            ),
        )
