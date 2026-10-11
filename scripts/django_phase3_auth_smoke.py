# ruff: noqa: E402
"""Exercise the Django Auth/User API against the Alembic-owned test schema."""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.test import Client

from taskiller.django_domain.models import TaskillerUser


def _bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    email = f"django-phase3-{uuid4().hex}@example.com"
    password = "Taskiller-phase3-password"
    client = Client()

    register = client.post(
        "/api/v1/auth/register",
        data={
            "email": email,
            "password": password,
            "displayName": "Django Phase 3",
            "timezone": "Europe/Istanbul",
            "locale": "en",
        },
        content_type="application/json",
        HTTP_USER_AGENT="Taskiller Phase 3 Smoke",
    )
    if register.status_code != 201:
        raise SystemExit(f"register failed: {register.status_code} {register.content!r}")
    register_body = register.json()
    token = register_body["accessToken"]
    if register_body["user"]["email"] != email:
        raise SystemExit("register response user contract mismatch")
    if "taskiller_refresh" not in register.cookies:
        raise SystemExit("register did not set refresh cookie")

    me = client.get("/api/v1/me", **_bearer(token))
    if me.status_code != 200:
        raise SystemExit(f"get me failed: {me.status_code} {me.content!r}")
    etag = me.headers.get("ETag")
    if not etag:
        raise SystemExit("get me returned no ETag")

    update = client.patch(
        "/api/v1/me",
        data={"displayName": "Django Phase 3 Updated"},
        content_type="application/json",
        HTTP_IF_MATCH=etag,
        **_bearer(token),
    )
    if update.status_code != 200:
        raise SystemExit(f"update me failed: {update.status_code} {update.content!r}")

    preferences = client.get("/api/v1/me/preferences", **_bearer(token))
    if preferences.status_code != 200:
        raise SystemExit(
            f"get preferences failed: {preferences.status_code} {preferences.content!r}"
        )
    preferences_etag = preferences.headers.get("ETag")
    pref_update = client.patch(
        "/api/v1/me/preferences",
        data={"preferredStrategy": "structured", "weekStartsOn": 1},
        content_type="application/json",
        HTTP_IF_MATCH=preferences_etag,
        **_bearer(token),
    )
    if pref_update.status_code != 200:
        raise SystemExit(
            f"update preferences failed: {pref_update.status_code} {pref_update.content!r}"
        )

    sessions = client.get("/api/v1/auth/sessions", **_bearer(token))
    if sessions.status_code != 200 or not sessions.json()["items"]:
        raise SystemExit(f"list sessions failed: {sessions.status_code} {sessions.content!r}")

    refresh = client.post("/api/v1/auth/refresh")
    if refresh.status_code != 200:
        raise SystemExit(f"refresh failed: {refresh.status_code} {refresh.content!r}")
    refreshed_token = refresh.json()["accessToken"]

    login_client = Client()
    login = login_client.post(
        "/api/v1/auth/login",
        data={
            "email": email,
            "password": password,
            "deviceName": "Secondary smoke device",
        },
        content_type="application/json",
    )
    if login.status_code != 200:
        raise SystemExit(f"login failed: {login.status_code} {login.content!r}")

    verification = client.post(
        "/api/v1/auth/email-verification/request",
        **_bearer(refreshed_token),
    )
    if verification.status_code != 202:
        raise SystemExit(
            f"email verification request failed: "
            f"{verification.status_code} {verification.content!r}"
        )

    reset = Client().post(
        "/api/v1/auth/password-reset/request",
        data={"email": email},
        content_type="application/json",
    )
    if reset.status_code != 202:
        raise SystemExit(f"password reset request failed: {reset.status_code} {reset.content!r}")

    export = client.post(
        "/api/v1/me/export-requests",
        HTTP_IDEMPOTENCY_KEY=f"phase3-{uuid4().hex}",
        **_bearer(refreshed_token),
    )
    if export.status_code != 202:
        raise SystemExit(f"export request failed: {export.status_code} {export.content!r}")
    export_id = export.json()["requestId"]
    export_detail = client.get(
        f"/api/v1/me/export-requests/{export_id}",
        **_bearer(refreshed_token),
    )
    if export_detail.status_code != 200:
        raise SystemExit(
            f"export detail failed: {export_detail.status_code} {export_detail.content!r}"
        )

    fresh_me = client.get("/api/v1/me", **_bearer(refreshed_token))
    deletion_etag = fresh_me.headers.get("ETag")
    deletion = client.delete(
        "/api/v1/me",
        HTTP_IF_MATCH=deletion_etag,
        **_bearer(refreshed_token),
    )
    if deletion.status_code != 202:
        raise SystemExit(f"account deletion failed: {deletion.status_code} {deletion.content!r}")
    if deletion.headers.get("Clear-Site-Data") != '"cookies", "storage"':
        raise SystemExit("account deletion Clear-Site-Data contract mismatch")

    if TaskillerUser.objects.get(email=email).is_active:
        raise SystemExit("account deletion did not deactivate user")

    print(
        "django phase-3 Auth/User smoke OK: register, profile, preferences, "
        "refresh, login, sessions, email requests, export, account deletion"
    )


if __name__ == "__main__":
    main()
