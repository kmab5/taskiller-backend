from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    release_sha: str | None
    release_branch: str | None
    release_repository: str | None


def build_metadata() -> BuildMetadata:
    return BuildMetadata(
        release_sha=(os.getenv("TASKILLER_RELEASE_SHA") or os.getenv("RENDER_GIT_COMMIT")),
        release_branch=(os.getenv("TASKILLER_RELEASE_BRANCH") or os.getenv("RENDER_GIT_BRANCH")),
        release_repository=(
            os.getenv("TASKILLER_RELEASE_REPOSITORY") or os.getenv("RENDER_GIT_REPO_SLUG")
        ),
    )
