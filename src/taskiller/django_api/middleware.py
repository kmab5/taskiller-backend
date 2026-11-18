from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from uuid import uuid4

from django.http import HttpRequest, HttpResponse, JsonResponse

from taskiller.core.config import Environment, get_settings

logger = logging.getLogger(__name__)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _request_id(request: HttpRequest) -> str:
    supplied = request.headers.get("x-request-id", "")
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return uuid4().hex


class TaskillerRuntimeMiddleware:
    """Cross-framework HTTP boundary parity for the Django migration API."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        settings = get_settings()
        request_id = _request_id(request)
        request.taskiller_request_id = request_id
        started = time.perf_counter()

        origin = request.headers.get("origin")
        allowed_origin = origin if origin and origin in settings.cors_origins else None

        if (
            request.method == "OPTIONS"
            and request.path.startswith(settings.api_prefix)
            and allowed_origin
        ):
            response = HttpResponse(status=204)
        elif (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.path.rstrip("/")
            in {
                f"{settings.api_prefix}/auth/{name}"
                for name in ("login", "register", "refresh", "logout", "logout-all")
            }
            and (
                (origin is not None and not allowed_origin)
                or (
                    origin is None
                    and request.headers.get("sec-fetch-site", "").lower() == "cross-site"
                )
            )
        ):
            response = JsonResponse(
                {
                    "type": "/problems/auth_origin_forbidden",
                    "code": "auth_origin_forbidden",
                    "title": "Untrusted request origin",
                    "status": 403,
                    "instance": request.path,
                    "requestId": request_id,
                },
                status=403,
                content_type="application/problem+json",
            )
            response["Cache-Control"] = "no-store"
        else:
            response = self.get_response(request)

        response["X-Request-ID"] = request_id
        if settings.security_headers_enabled:
            if "X-Content-Type-Options" not in response:
                response["X-Content-Type-Options"] = "nosniff"
            if "X-Frame-Options" not in response:
                response["X-Frame-Options"] = "DENY"
            if "Referrer-Policy" not in response:
                response["Referrer-Policy"] = "no-referrer"
            if "Permissions-Policy" not in response:
                response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            if request.path.startswith(settings.api_prefix) and "Cache-Control" not in response:
                response["Cache-Control"] = "no-store"
            if (
                settings.env is Environment.PRODUCTION
                and settings.hsts_max_age_seconds
                and "Strict-Transport-Security" not in response
            ):
                response["Strict-Transport-Security"] = (
                    f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
                )

        if allowed_origin:
            response["Access-Control-Allow-Origin"] = allowed_origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Idempotency-Key, If-Match, X-Request-ID"
            )
            response["Access-Control-Expose-Headers"] = "ETag, Location, Retry-After, X-Request-ID"

        request.taskiller_duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "path": request.path,
                "status": response.status_code,
                "duration_ms": request.taskiller_duration_ms,
            },
        )
        return response
