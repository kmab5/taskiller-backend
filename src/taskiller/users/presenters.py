from taskiller.db.models import User, UserPreferences
from taskiller.users.schemas import UserPreferencesResponse, UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )


def preferences_to_response(preferences: UserPreferences) -> UserPreferencesResponse:
    return UserPreferencesResponse(
        timezone=preferences.timezone,
        locale=preferences.locale,
        week_starts_on=preferences.week_starts_on,
        preferred_strategy=preferences.preferred_strategy,
        preferred_work_block_min_seconds=preferences.preferred_work_block_min_seconds,
        preferred_work_block_max_seconds=preferences.preferred_work_block_max_seconds,
        show_review_prompt=preferences.show_review_prompt,
        version=preferences.version,
    )
