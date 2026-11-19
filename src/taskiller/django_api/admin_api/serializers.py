from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError("Unknown fields or invalid object.")
        return super().to_internal_value(data)


class CsrfResponse(serializers.Serializer):
    csrfToken = serializers.CharField()


class LoginRequest(StrictSerializer):
    username = serializers.CharField(max_length=150, trim_whitespace=False)
    password = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class ChallengeResponse(serializers.Serializer):
    challengeId = serializers.UUIDField()
    expiresAt = serializers.DateTimeField()
    next = serializers.CharField()


class MfaRequest(StrictSerializer):
    challengeId = serializers.UUIDField()
    code = serializers.CharField(max_length=64, trim_whitespace=True)


class StepUpRequest(StrictSerializer):
    code = serializers.CharField(max_length=64, trim_whitespace=True)


class EnrollmentRequest(StrictSerializer):
    invitationToken = serializers.CharField(max_length=200, write_only=True)
    password = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class EnrollmentChallengeResponse(ChallengeResponse):
    secret = serializers.CharField()
    provisioningUri = serializers.CharField()


class EnrollmentResponse(serializers.Serializer):
    enrolled = serializers.BooleanField()
    recoveryCodes = serializers.ListField(child=serializers.CharField())


class StaffMeResponse(serializers.Serializer):
    staffId = serializers.UUIDField()
    username = serializers.CharField()
    displayName = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    roles = serializers.ListField(child=serializers.CharField())
    expiresAt = serializers.DateTimeField()
    idleExpiresAt = serializers.DateTimeField()
    mfaVerifiedAt = serializers.DateTimeField()
    version = serializers.IntegerField()
