from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from taskiller.core.problems import PROBLEM_CODES

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def install_openapi_contract(app: FastAPI, *, api_prefix: str) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            openapi_version=app.openapi_version,
        )
        components = schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        schemas["Problem"] = {
            "type": "object",
            "required": ["type", "title", "status", "code", "instance"],
            "properties": {
                "type": {"type": "string", "example": "/problems/validation_error"},
                "title": {"type": "string"},
                "status": {"type": "integer", "minimum": 400, "maximum": 599},
                "code": {"type": "string"},
                "instance": {"type": "string"},
                "requestId": {"type": "string"},
                "detail": {"type": "string"},
                "meta": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        }
        problem_response = {
            "description": "Taskiller problem response",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        }
        for path, path_item in schema.get("paths", {}).items():
            if not path.startswith(api_prefix):
                continue
            for method, operation in path_item.items():
                if method in _HTTP_METHODS:
                    operation.setdefault("responses", {}).setdefault("default", problem_response)
        schema["x-taskiller-problem-codes"] = sorted(PROBLEM_CODES)
        schema["x-taskiller-api-prefix"] = api_prefix
        app.openapi_schema = schema
        return schema

    setattr(app, "openapi", custom_openapi)  # noqa: B010 - FastAPI custom OpenAPI hook
