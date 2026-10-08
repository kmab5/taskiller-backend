from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularSwaggerView

from taskiller.django_project import contract_views, health

admin.site.site_header = "Taskiller Administration"
admin.site.site_title = "Taskiller Admin"
admin.site.index_title = "Read-only migration bridge"

urlpatterns = [
    path("", include("taskiller.django_api.urls")),
    path("openapi.json", contract_views.canonical_openapi, name="canonical-openapi"),
    path("docs", SpectacularSwaggerView.as_view(url_name="canonical-openapi"), name="docs"),
    path("admin/", admin.site.urls),
    path("health/live", health.live, name="django-health-live"),
    path("health/ready", health.ready, name="django-health-ready"),
    path("health/version", health.version, name="django-health-version"),
]
