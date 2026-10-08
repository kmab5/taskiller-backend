from __future__ import annotations

from typing import Any

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class TaskillerAPIError(Exception):
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


def _problem(
    request: object,
    error: TaskillerAPIError,
) -> Response:
    path = getattr(request, "path", "")
    body: dict[str, Any] = {
        "type": f"/problems/{error.code}",
        "title": error.title,
        "status": error.status_code,
        "code": error.code,
        "instance": path,
    }
    request_id = getattr(request, "taskiller_request_id", None)
    if request_id:
        body["requestId"] = request_id
    if error.detail:
        body["detail"] = error.detail
    if error.meta:
        body["meta"] = error.meta

    response = Response(
        body,
        status=error.status_code,
        content_type="application/problem+json",
    )
    for key, value in error.headers.items():
        response[key] = value
    response.setdefault("Cache-Control", "no-store")
    return response


def _validation_meta(detail: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if isinstance(detail, dict):
        for field, value in detail.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                errors.append(
                    {
                        "type": getattr(item, "code", "invalid"),
                        "loc": ["body", str(field)],
                        "msg": str(item),
                    }
                )
    elif isinstance(detail, list):
        for item in detail:
            errors.append(
                {
                    "type": getattr(item, "code", "invalid"),
                    "loc": ["body"],
                    "msg": str(item),
                }
            )
    else:
        errors.append({"type": "invalid", "loc": ["body"], "msg": str(detail)})
    return errors


def taskiller_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    request = context.get("request")

    if isinstance(exc, TaskillerAPIError):
        return _problem(request, exc)

    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        return _problem(
            request,
            TaskillerAPIError(
                401,
                "invalid_access_token",
                "Authentication required",
                "The access token is missing, invalid, expired, or belongs to a revoked session.",
                headers={"WWW-Authenticate": "Bearer"},
            ),
        )

    if isinstance(exc, exceptions.ValidationError):
        return _problem(
            request,
            TaskillerAPIError(
                422,
                "validation_error",
                "Request validation failed",
                "One or more request values are invalid.",
                meta={"errors": _validation_meta(exc.detail)},
            ),
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return _problem(
                request,
                TaskillerAPIError(404, "not_found", "Resource not found"),
            )
        return response

    return _problem(
        request,
        TaskillerAPIError(
            500,
            "internal_error",
            "Internal server error",
            "The request could not be completed.",
        ),
    )
