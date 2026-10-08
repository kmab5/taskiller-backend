from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from taskiller.django_domain.models import TaskillerUser


class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=10, max_length=256, write_only=True)
    displayName = serializers.CharField(
        source="display_name",
        max_length=200,
        allow_blank=True,
        allow_null=True,
        required=False,
        default=None,
    )
    timezone = serializers.CharField(max_length=100, required=False, default="UTC")
    locale = serializers.CharField(max_length=40, required=False, default="en")

    def validate_displayName(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Unknown IANA timezone") from exc
        return value


class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=1, max_length=256, write_only=True)
    deviceName = serializers.CharField(
        source="device_name",
        max_length=200,
        allow_blank=True,
        allow_null=True,
        required=False,
        default=None,
    )


class EmailVerificationConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=512)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=512)
    newPassword = serializers.CharField(
        source="new_password",
        min_length=10,
        max_length=256,
        write_only=True,
    )


class UpdateUserSerializer(serializers.Serializer):
    displayName = serializers.CharField(
        source="display_name",
        max_length=200,
        allow_blank=True,
        allow_null=True,
        required=False,
    )

    def validate_displayName(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UpdatePreferencesSerializer(serializers.Serializer):
    timezone = serializers.CharField(max_length=100, allow_null=True, required=False)
    locale = serializers.CharField(max_length=40, allow_null=True, required=False)
    weekStartsOn = serializers.IntegerField(
        source="week_starts_on",
        min_value=0,
        max_value=6,
        allow_null=True,
        required=False,
    )
    preferredStrategy = serializers.ChoiceField(
        source="preferred_strategy",
        choices=("auto", "continuous", "structured", "flexible"),
        allow_null=True,
        required=False,
    )
    preferredWorkBlockMinSeconds = serializers.IntegerField(
        source="preferred_work_block_min_seconds",
        min_value=60,
        max_value=21600,
        allow_null=True,
        required=False,
    )
    preferredWorkBlockMaxSeconds = serializers.IntegerField(
        source="preferred_work_block_max_seconds",
        min_value=60,
        max_value=21600,
        allow_null=True,
        required=False,
    )
    showReviewPrompt = serializers.BooleanField(
        source="show_review_prompt",
        allow_null=True,
        required=False,
    )

    def validate_timezone(self, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Unknown IANA timezone") from exc
        return value

    def validate_locale(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("locale must not be blank")
        return cleaned

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        minimum = attrs.get("preferred_work_block_min_seconds")
        maximum = attrs.get("preferred_work_block_max_seconds")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError("preferred minimum work block cannot exceed maximum")
        return attrs


class UserResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.CharField()
    displayName = serializers.CharField(source="display_name", allow_null=True)
    emailVerified = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at")
    updatedAt = serializers.DateTimeField(source="updated_at")
    version = serializers.IntegerField()

    def get_emailVerified(self, obj: TaskillerUser) -> bool:
        return obj.email_verified_at is not None


class AuthResponseSerializer(serializers.Serializer):
    accessToken = serializers.CharField()
    tokenType = serializers.CharField()
    expiresIn = serializers.IntegerField()
    user = UserResponseSerializer()


class AuthSessionResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    deviceName = serializers.CharField(source="device_name", allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at")
    lastUsedAt = serializers.DateTimeField(source="last_used_at", allow_null=True)
    expiresAt = serializers.DateTimeField(source="expires_at")
    current = serializers.BooleanField()


class AuthSessionsResponseSerializer(serializers.Serializer):
    items = AuthSessionResponseSerializer(many=True)


class UserPreferencesResponseSerializer(serializers.Serializer):
    timezone = serializers.CharField()
    locale = serializers.CharField()
    weekStartsOn = serializers.IntegerField(source="week_starts_on")
    preferredStrategy = serializers.CharField(source="preferred_strategy")
    preferredWorkBlockMinSeconds = serializers.IntegerField(
        source="preferred_work_block_min_seconds",
        allow_null=True,
    )
    preferredWorkBlockMaxSeconds = serializers.IntegerField(
        source="preferred_work_block_max_seconds",
        allow_null=True,
    )
    showReviewPrompt = serializers.BooleanField(source="show_review_prompt")
    version = serializers.IntegerField()


class DataExportResponseSerializer(serializers.Serializer):
    requestId = serializers.UUIDField()
    status = serializers.CharField()
    createdAt = serializers.DateTimeField()
    startedAt = serializers.DateTimeField(allow_null=True)
    completedAt = serializers.DateTimeField(allow_null=True)
    expiresAt = serializers.DateTimeField(allow_null=True)
    archiveSizeBytes = serializers.IntegerField(allow_null=True)
    archiveSha256 = serializers.CharField(allow_null=True)
    downloadUrl = serializers.CharField(allow_null=True)
    failureCode = serializers.CharField(allow_null=True)


class AccountDeletionResponseSerializer(serializers.Serializer):
    requestId = serializers.UUIDField()
    status = serializers.CharField()
    requestedAt = serializers.DateTimeField()
    executeAfter = serializers.DateTimeField()
