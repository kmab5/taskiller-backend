from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from taskiller.core.config import Environment, Settings

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    release_sha: str | None
    release_branch: str | None
    release_repository: str | None


def build_metadata() -> BuildMetadata:
    return BuildMetadata(
        release_sha=(
            os.getenv("TASKILLER_RELEASE_SHA")
            or os.getenv("RENDER_GIT_COMMIT")
            or os.getenv("KOYEB_GIT_SHA")
        ),
        release_branch=(
            os.getenv("TASKILLER_RELEASE_BRANCH")
            or os.getenv("RENDER_GIT_BRANCH")
            or os.getenv("KOYEB_GIT_BRANCH")
        ),
        release_repository=(
            os.getenv("TASKILLER_RELEASE_REPOSITORY")
            or os.getenv("RENDER_GIT_REPO_SLUG")
            or os.getenv("KOYEB_GIT_REPOSITORY")
        ),
    )


def request_client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Render places the real client address first in X-Forwarded-For.
            candidate = forwarded.split(",", 1)[0].strip()
            if candidate:
                return candidate[:100]
    return (request.client.host if request.client is not None else "unknown")[:100]


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid4().hex


def install_runtime_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            status_code = response.status_code if response is not None else 500
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                if settings.security_headers_enabled:
                    response.headers.setdefault("X-Content-Type-Options", "nosniff")
                    response.headers.setdefault("X-Frame-Options", "DENY")
                    response.headers.setdefault("Referrer-Policy", "no-referrer")
                    response.headers.setdefault(
                        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
                    )
                    if request.url.path.startswith(settings.api_prefix):
                        response.headers.setdefault("Cache-Control", "no-store")
                    if settings.env is Environment.PRODUCTION and settings.hsts_max_age_seconds:
                        response.headers.setdefault(
                            "Strict-Transport-Security",
                            f"max-age={settings.hsts_max_age_seconds}; includeSubDomains",
                        )
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request_client_ip(request, settings),
                },
            )
