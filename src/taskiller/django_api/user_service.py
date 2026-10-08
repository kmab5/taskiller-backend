from __future__ import annotations

from django.db import transaction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_domain.models import TaskillerUser, UserPreferences
from taskiller.users.etag import make_etag


def require_etag(if_match: str | None, expected: str) -> None:
    if if_match is None or if_match.strip() != expected:
        raise TaskillerAPIError(
            412,
            "precondition_failed",
            "Resource version mismatch",
            "Refresh the resource and retry using its latest ETag.",
            headers={"ETag": expected},
        )


def update_user(
    user_id: object,
    payload: dict[str, object],
    if_match: str | None,
) -> TaskillerUser:
    with transaction.atomic():
        user = TaskillerUser.objects.select_for_update().get(id=user_id)
        require_etag(if_match, make_etag("user", user.id, user.version))
        if "display_name" in payload:
            user.display_name = payload["display_name"]
            user.version += 1
            user.updated_at = utc_now()
            user.save(update_fields=["display_name", "version", "updated_at"])
        return user


def update_preferences(
    user_id: object,
    payload: dict[str, object],
    if_match: str | None,
) -> UserPreferences:
    with transaction.atomic():
        preferences = UserPreferences.objects.select_for_update().get(user_id=user_id)
        require_etag(
            if_match,
            make_etag("preferences", preferences.user_id, preferences.version),
        )

        if "timezone" in payload and payload["timezone"] is not None:
            try:
                ZoneInfo(str(payload["timezone"]))
            except ZoneInfoNotFoundError as exc:
                raise TaskillerAPIError(
                    422,
                    "invalid_timezone",
                    "Invalid timezone",
                    "timezone must be a valid IANA timezone name.",
                ) from exc

        for field, value in payload.items():
            setattr(preferences, field, value)

        if (
            preferences.preferred_work_block_min_seconds is not None
            and preferences.preferred_work_block_max_seconds is not None
            and preferences.preferred_work_block_min_seconds
            > preferences.preferred_work_block_max_seconds
        ):
            raise TaskillerAPIError(
                422,
                "invalid_preferred_work_block_range",
                "Invalid preferred work block range",
                "The preferred minimum work block cannot exceed the preferred maximum.",
            )

        if payload:
            preferences.version += 1
            preferences.updated_at = utc_now()
            preferences.save(
                update_fields=[
                    *payload.keys(),
                    "version",
                    "updated_at",
                ]
            )
        return preferences
