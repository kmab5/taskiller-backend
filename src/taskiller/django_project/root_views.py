"""The backend root sends human visitors to the configured application."""

from __future__ import annotations

from django.http import HttpResponseRedirect
from django.views.decorators.http import require_safe

from taskiller.core.config import get_settings


@require_safe
def frontend_redirect(_request):
    response = HttpResponseRedirect(get_settings().web_app_url)
    response["Cache-Control"] = "no-store"
    return response
