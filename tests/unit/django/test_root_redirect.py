from __future__ import annotations

import pytest
from django.test import RequestFactory
from django.urls import resolve

from taskiller.core.config import Settings
from taskiller.django_project import root_views


@pytest.mark.parametrize("method", ["get", "head"])
@pytest.mark.parametrize("url", ["https://taskiller.example", "https://new.example/app"])
def test_root_redirect_uses_registered_frontend(monkeypatch, method, url):
    monkeypatch.setenv("TASKILLER_WEB_APP_URL", url)
    config = Settings(_env_file=None)
    monkeypatch.setattr(root_views, "get_settings", lambda: config)
    route = resolve("/")
    assert route.url_name == "frontend-home"
    response = route.func(getattr(RequestFactory(), method)("/?token=do-not-forward"))
    assert response.status_code == 302
    assert response["Location"] == url
    assert response["Cache-Control"] == "no-store"


def test_root_does_not_redirect_mutations():
    response = resolve("/").func(RequestFactory().post("/", {"private": "body"}))
    assert response.status_code == 405
    assert "Location" not in response


@pytest.mark.parametrize(
    "path", ["/api/v1/me", "/admin/", "/docs", "/health/live", "/openapi.json"]
)
def test_root_redirect_does_not_capture_existing_routes(path):
    assert resolve(path).func is not root_views.frontend_redirect
