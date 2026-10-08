from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.urls import resolve

from taskiller.django_api.authentication import TaskillerBearerAuthentication
from taskiller.django_domain.models import TaskillerUser


def test_taskiller_user_is_valid_drf_principal() -> None:
    assert TaskillerUser.is_authenticated.fget is not None
    assert TaskillerUser.is_anonymous.fget is not None


def test_authentication_scheme_is_bearer() -> None:
    authentication = TaskillerBearerAuthentication()
    assert authentication.authenticate_header(None) == "Bearer"


def test_core_auth_user_paths_resolve() -> None:
    assert resolve("/api/v1/auth/register").url_name is None
    assert resolve("/api/v1/auth/login").url_name is None
    assert resolve("/api/v1/me").url_name is None
    assert resolve("/api/v1/me/preferences").url_name is None
