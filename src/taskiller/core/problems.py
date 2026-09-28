from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
    if error.detail:
        body["detail"] = error.detail
    if error.meta:
        body["meta"] = error.meta
    return JSONResponse(
        status_code=error.status_code,
        content=body,
        media_type="application/problem+json",
        headers=error.headers,
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
                    for item in exc.errors(include_url=False)
                ]
            },
        )
        return problem_response(request, error)
