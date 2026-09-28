from uuid import UUID

from taskiller.core.problems import ApiError


def make_etag(kind: str, resource_id: UUID, version: int) -> str:
    return f'"{kind}:{resource_id}:v{version}"'


def require_etag(if_match: str | None, expected: str) -> None:
    if if_match is None or if_match.strip() != expected:
        raise ApiError(
            412,
            "precondition_failed",
            "Resource version mismatch",
            "Refresh the resource and retry using its latest ETag.",
            headers={"ETag": expected},
        )
