from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not hasattr(data, "keys") or set(data.keys()) - set(self.fields):
            raise serializers.ValidationError("Unknown or malformed filters.")
        if hasattr(data, "getlist") and any(len(data.getlist(k)) != 1 for k in data):
            raise serializers.ValidationError("Repeated filters are not allowed.")
        return super().to_internal_value(data)


class ReadFiltersSerializer(StrictSerializer):
    cursor = serializers.CharField(required=False, max_length=2048)
    limit = serializers.IntegerField(default=25, min_value=1, max_value=100)
    start = serializers.DateTimeField(required=False, default_timezone=UTC)
    end = serializers.DateTimeField(required=False, default_timezone=UTC)

    def validate(self, attrs):
        now = datetime.now(UTC)
        end = attrs.setdefault("end", now)
        start = attrs.setdefault("start", end - timedelta(days=30))
        if start >= end or end - start > timedelta(days=90) or end > now:
            raise serializers.ValidationError("Use a past UTC range of at most 90 days.")
        return attrs


class UserFiltersSerializer(ReadFiltersSerializer):
    start = serializers.DateTimeField(
        required=False,
        default_timezone=UTC,
        help_text=(
            "Optional inclusive registration timestamp. "
            "Omit to include accounts of any age; no 90-day limit."
        ),
    )
    end = serializers.DateTimeField(
        required=False,
        default_timezone=UTC,
        help_text=(
            "Optional exclusive registration timestamp; "
            "defaults to request time and is preserved by the cursor."
        ),
    )
    query = serializers.CharField(required=False, min_length=3, max_length=200)
    lifecycle = serializers.ChoiceField(
        choices=["active", "suspended", "pending_deletion", "inactive"], required=False
    )
    verified = serializers.BooleanField(required=False)

    def validate(self, attrs):
        # Account discovery must include older registrations, unlike activity reports.
        now = datetime.now(UTC)
        end = attrs.setdefault("end", now)
        start = attrs.get("start")
        if end > now or (start is not None and start >= end):
            raise serializers.ValidationError("Use a past UTC range with start before end.")
        return attrs


class JobFiltersSerializer(ReadFiltersSerializer):
    type = serializers.ChoiceField(
        choices=["auth_email", "retention", "data_export", "account_delete"], required=False
    )
    state = serializers.ChoiceField(
        choices=["queued", "running", "completed", "dead"], required=False
    )


class PrivacyFiltersSerializer(ReadFiltersSerializer):
    type = serializers.ChoiceField(choices=["export", "deletion"], required=True)
    state = serializers.ChoiceField(
        choices=["queued", "pending", "scheduled", "running", "completed", "failed", "cancelled"],
        required=False,
    )
    userId = serializers.UUIDField(required=False)


class AuditFiltersSerializer(ReadFiltersSerializer):
    actor = serializers.CharField(max_length=40, required=False)
    target = serializers.CharField(max_length=80, required=False)
    action = serializers.RegexField(r"^[a-zA-Z0-9_.:-]{1,100}$", required=False)
    outcome = serializers.ChoiceField(choices=["success", "denied", "failed"], required=False)


class WorkFiltersSerializer(ReadFiltersSerializer):
    kind = serializers.ChoiceField(
        choices=["project", "sprint", "chore", "work_type", "focus_plan", "execution_session"],
        required=True,
    )


class UserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    displayName = serializers.CharField(allow_null=True)
    lifecycle = serializers.ChoiceField(
        choices=["active", "suspended", "pending_deletion", "inactive"]
    )
    emailVerified = serializers.BooleanField()
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    updatedAt = serializers.DateTimeField(default_timezone=UTC)
    version = serializers.IntegerField()


class SessionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    deviceName = serializers.CharField(allow_null=True)
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    lastUsedAt = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    expiresAt = serializers.DateTimeField(default_timezone=UTC)
    revokedAt = serializers.DateTimeField(allow_null=True, default_timezone=UTC)


class ActivitySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=["execution_event", "security_event"])
    type = serializers.CharField()
    timestamp = serializers.DateTimeField(default_timezone=UTC)


class JobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.CharField()
    state = serializers.CharField()
    attempts = serializers.IntegerField()
    maxAttempts = serializers.IntegerField()
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    updatedAt = serializers.DateTimeField(default_timezone=UTC)
    availableAt = serializers.DateTimeField(default_timezone=UTC)
    eligibleActions = serializers.ListField(child=serializers.CharField())


class PrivacySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    userId = serializers.UUIDField()
    type = serializers.ChoiceField(choices=["export", "deletion"])
    state = serializers.CharField()
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    completedAt = serializers.DateTimeField(allow_null=True, default_timezone=UTC)


class AuditChangesSerializer(serializers.Serializer):
    state = serializers.CharField(required=False)
    status = serializers.CharField(required=False)
    version = serializers.IntegerField(required=False)
    enabled = serializers.BooleanField(required=False)
    sessionCount = serializers.IntegerField(required=False)
    attempts = serializers.IntegerField(required=False)
    isActive = serializers.BooleanField(required=False)
    suspended = serializers.BooleanField(required=False)
    count = serializers.IntegerField(required=False)
    jobType = serializers.CharField(required=False)
    roles = serializers.ListField(child=serializers.CharField(), required=False)
    capabilities = serializers.ListField(child=serializers.CharField(), required=False)


class AuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    actorId = serializers.CharField(allow_null=True)
    action = serializers.CharField()
    targetType = serializers.CharField()
    targetId = serializers.CharField()
    timestamp = serializers.DateTimeField(default_timezone=UTC)
    requestId = serializers.CharField(allow_blank=True)
    outcome = serializers.CharField()
    reasonCode = serializers.CharField(allow_blank=True, allow_null=True)
    changes = AuditChangesSerializer()


class StaffSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    etag = serializers.CharField(
        help_text="Use as If-Match for staff commands; staff:{id}:v{version}."
    )
    userId = serializers.CharField()
    displayName = serializers.CharField()
    enabled = serializers.BooleanField()
    mfaEnrolled = serializers.BooleanField()
    roles = serializers.ListField(child=serializers.CharField())
    capabilities = serializers.ListField(child=serializers.CharField())
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    version = serializers.IntegerField()


class RoleSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.IntegerField()
    capabilities = serializers.ListField(child=serializers.CharField())


class WorkSegmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    segmentIndex = serializers.IntegerField()
    kind = serializers.CharField()
    durationMode = serializers.CharField()
    targetSeconds = serializers.IntegerField(allow_null=True)
    minSeconds = serializers.IntegerField(allow_null=True)
    maxSeconds = serializers.IntegerField(allow_null=True)
    linkedWorkItemId = serializers.UUIDField(allow_null=True)
    optional = serializers.BooleanField()
    label = serializers.CharField(allow_null=True)


class WorkSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    ownerId = serializers.UUIDField(allow_null=True)
    kind = serializers.CharField()
    name = serializers.CharField(allow_null=True)
    state = serializers.CharField(allow_null=True)
    parentId = serializers.UUIDField(allow_null=True)
    workItemId = serializers.UUIDField(allow_null=True)
    focusPlanId = serializers.UUIDField(allow_null=True)
    createdAt = serializers.DateTimeField(default_timezone=UTC)
    updatedAt = serializers.DateTimeField(default_timezone=UTC)
    version = serializers.IntegerField()

    # Detail-only fields are omitted from list projections and other work kinds.
    description = serializers.CharField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, allow_null=True)
    workTypeId = serializers.UUIDField(required=False, allow_null=True)
    dueAt = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default_timezone=UTC,
        help_text="WorkItem.deadline_at in UTC.",
    )
    plannedStartAt = serializers.DateTimeField(
        required=False, allow_null=True, default_timezone=UTC
    )
    estimatedEffortSeconds = serializers.IntegerField(required=False, allow_null=True)
    targetStartDate = serializers.DateField(required=False, allow_null=True)
    targetEndDate = serializers.DateField(required=False, allow_null=True)
    completedAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)
    cancelledAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)
    archivedAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)
    deletedAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)
    slug = serializers.CharField(required=False)
    isSystem = serializers.BooleanField(required=False)
    cognitiveDemand = serializers.CharField(required=False)
    interruptionSensitivity = serializers.CharField(required=False)
    continuityNeed = serializers.CharField(required=False)
    repetitiveness = serializers.CharField(required=False)
    physicality = serializers.CharField(required=False)
    learningMode = serializers.CharField(required=False)
    source = serializers.CharField(required=False)
    isTemplate = serializers.BooleanField(required=False)
    segments = WorkSegmentSerializer(many=True, required=False)
    currentSegmentIndex = serializers.IntegerField(required=False)
    sessionStartedAt = serializers.DateTimeField(required=False, default_timezone=UTC)
    currentSegmentStartedAt = serializers.DateTimeField(
        required=False, allow_null=True, default_timezone=UTC
    )
    pausedAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)
    endedAt = serializers.DateTimeField(required=False, allow_null=True, default_timezone=UTC)

    def to_representation(self, instance):
        result = super().to_representation(instance)
        # DRF otherwise emits null for absent optional nullable detail fields.
        return {key: value for key, value in result.items() if key in instance}


class OverviewSerializer(serializers.Serializer):
    start = serializers.DateTimeField(default_timezone=UTC)
    end = serializers.DateTimeField(default_timezone=UTC)
    observedAt = serializers.DateTimeField(default_timezone=UTC)
    registrations = serializers.IntegerField()
    completedExecutionSessions = serializers.IntegerField()
    accountsWithExecutionActivity = serializers.IntegerField()
    queuedJobs = serializers.IntegerField(allow_null=True)
    failedJobs = serializers.IntegerField(allow_null=True)
    latestWorkerSignalAt = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    workerSignalSource = serializers.CharField(allow_null=True)


def page_serializer(name, item_serializer):
    return type(
        name,
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "items": item_serializer(many=True),
            "nextCursor": serializers.CharField(allow_null=True),
        },
    )


UserPageSerializer = page_serializer("AdminUserPage", UserSerializer)
SessionPageSerializer = page_serializer("AdminSessionPage", SessionSerializer)
ActivityPageSerializer = page_serializer("AdminActivityPage", ActivitySerializer)
JobPageSerializer = page_serializer("AdminJobPage", JobSerializer)
PrivacyPageSerializer = page_serializer("AdminPrivacyPage", PrivacySerializer)
AuditPageSerializer = page_serializer("AdminAuditPage", AuditSerializer)
StaffPageSerializer = page_serializer("AdminStaffPage", StaffSerializer)
WorkPageSerializer = page_serializer("AdminWorkPage", WorkSerializer)
