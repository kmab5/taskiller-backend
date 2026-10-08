from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def canonical_openapi(_request: object) -> JsonResponse:
    path = Path(settings.BASE_DIR) / "openapi" / "current.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    response = JsonResponse(schema)
    response["Cache-Control"] = "public, max-age=300"
    return response
