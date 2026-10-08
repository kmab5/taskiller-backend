from typing import Annotated

from fastapi import APIRouter, Header, Response
from sqlalchemy import select

from taskiller.auth.dependencies import CurrentAuth
from taskiller.core.problems import ApiError
from taskiller.core.time import utc_now
from taskiller.db.dependencies import DbSession
from taskiller.db.models import User, UserPreferences
from taskiller.users.etag import make_etag, require_etag
from taskiller.users.presenters import preferences_to_response, user_to_response
from taskiller.users.schemas import (
    UpdatePreferencesRequest,
    UpdateUserRequest,
    UserPreferencesResponse,
    UserResponse,
)

router = APIRouter(tags=["User"])


@router.get("/me", response_model=UserResponse, operation_id="getMe")
async def get_me(response: Response, auth: CurrentAuth) -> UserResponse:
    response.headers["ETag"] = make_etag("user", auth.user.id, auth.user.version)
    return user_to_response(auth.user)


@router.patch("/me", response_model=UserResponse, operation_id="updateMe")
async def update_me(
    payload: UpdateUserRequest,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> UserResponse:
    user = (
        await db.execute(
            select(User)
            .where(User.id == auth.user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    current_etag = make_etag("user", user.id, user.version)
    require_etag(if_match, current_etag)
    if payload.model_fields_set:
        user.display_name = payload.display_name
        user.version += 1
        user.updated_at = utc_now()
        await db.commit()
    response.headers["ETag"] = make_etag("user", user.id, user.version)
    return user_to_response(user)


@router.get(
    "/me/preferences", response_model=UserPreferencesResponse, operation_id="getPreferences"
)
async def get_preferences(
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
) -> UserPreferencesResponse:
    preferences = (
        await db.execute(select(UserPreferences).where(UserPreferences.user_id == auth.user.id))
    ).scalar_one()
    response.headers["ETag"] = make_etag("preferences", auth.user.id, preferences.version)
    return preferences_to_response(preferences)


@router.patch(
    "/me/preferences",
    response_model=UserPreferencesResponse,
    operation_id="updatePreferences",
)
async def update_preferences(
    payload: UpdatePreferencesRequest,
    response: Response,
    db: DbSession,
    auth: CurrentAuth,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> UserPreferencesResponse:
    preferences = (
        await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == auth.user.id).with_for_update()
        )
    ).scalar_one()
    current_etag = make_etag("preferences", auth.user.id, preferences.version)
    require_etag(if_match, current_etag)

    fields = payload.model_fields_set
    if fields:
        for field in fields:
            setattr(preferences, field, getattr(payload, field))
        if (
            preferences.preferred_work_block_min_seconds is not None
            and preferences.preferred_work_block_max_seconds is not None
            and preferences.preferred_work_block_min_seconds
            > preferences.preferred_work_block_max_seconds
        ):
            raise ApiError(
                422,
                "invalid_preferred_work_block_range",
                "Invalid preferred work block range",
                "The preferred minimum work block cannot exceed the preferred maximum.",
            )
        preferences.version += 1
        preferences.updated_at = utc_now()
        await db.commit()

    response.headers["ETag"] = make_etag("preferences", auth.user.id, preferences.version)
    return preferences_to_response(preferences)
