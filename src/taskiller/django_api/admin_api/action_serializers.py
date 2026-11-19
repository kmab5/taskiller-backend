"""Strict command inputs; private corrections use the existing domain schemas."""

from rest_framework import serializers

ROLES = ("Owner", "Administrator", "Support", "Analyst")
ACCOUNT_ACTIONS = ("suspend", "reactivate", "recovery-email", "revoke-sessions")
WORK_ACTIONS = ("update-item", "update-type", "update-plan", "session-event")
BULK_ACTIONS = (
    *ACCOUNT_ACTIONS,
    "staff.roles",
    "staff.revoke-access",
    "jobs.retry",
    "privacy.export",
    "privacy.deletion",
    "work.correct",
)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError("Unknown fields or invalid object.")
        return super().to_internal_value(data)


class ReasonSerializer(StrictSerializer):
    reasonCode = serializers.RegexField(r"^[a-z][a-z0-9_]{1,63}$", max_length=64)
    comment = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)


class CommandSerializer(StrictSerializer):
    reason = ReasonSerializer()


class AccountCommandSerializer(CommandSerializer):
    sessionId = serializers.UUIDField(required=False)


class InvitationSerializer(CommandSerializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ROLES), min_length=1, max_length=4
    )

    def validate_roles(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate roles are not allowed.")
        return sorted(value)


class RolesSerializer(CommandSerializer):
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ROLES), max_length=4, allow_empty=True
    )
    validate_roles = InvitationSerializer.validate_roles


class WorkCorrectionSerializer(CommandSerializer):
    operation = serializers.ChoiceField(choices=WORK_ACTIONS)
    correction = serializers.DictField(allow_empty=False)


class BulkTargetSerializer(StrictSerializer):
    id = serializers.UUIDField()
    etag = serializers.CharField(max_length=200, required=False)
    sessionId = serializers.UUIDField(required=False)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ROLES), max_length=4, required=False
    )
    operation = serializers.ChoiceField(choices=WORK_ACTIONS, required=False)
    correction = serializers.DictField(allow_empty=False, required=False)


class BulkCommandSerializer(CommandSerializer):
    action = serializers.ChoiceField(choices=BULK_ACTIONS)
    targets = BulkTargetSerializer(many=True, min_length=1, max_length=50)

    def validate_targets(self, value):
        ids = [str(item["id"]) for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate targets are not allowed.")
        return value


class CommandResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    targetId = serializers.CharField(required=False)
    etag = serializers.CharField(required=False)
    requestId = serializers.CharField(required=False)
    invitationId = serializers.UUIDField(required=False)
    invitationToken = serializers.CharField(required=False)
    expiresAt = serializers.DateTimeField(required=False)
    replayed = serializers.BooleanField(required=False)
    detail = serializers.CharField(required=False)


class BulkResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    eligibleCount = serializers.IntegerField(required=False)
    results = serializers.ListField(child=serializers.DictField())
