from __future__ import annotations

from django.contrib import admin
from django.db import models

from taskiller.django_domain import models as domain


class ReadOnlyTaskillerAdmin(admin.ModelAdmin):
    """Operational visibility without allowing Django to mutate Alembic-owned rows."""

    show_full_result_count = False
    list_per_page = 50

    def has_add_permission(self, request: object) -> bool:
        del request
        return False

    def has_change_permission(
        self,
        request: object,
        obj: models.Model | None = None,
    ) -> bool:
        del request, obj
        return False

    def has_delete_permission(
        self,
        request: object,
        obj: models.Model | None = None,
    ) -> bool:
        del request, obj
        return False

    def get_readonly_fields(
        self,
        request: object,
        obj: models.Model | None = None,
    ) -> tuple[str, ...]:
        del request, obj
        return tuple(field.name for field in self.model._meta.fields)


@admin.register(domain.TaskillerUser)
class TaskillerUserAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "email",
        "display_name",
        "is_active",
        "email_verified_at",
        "created_at",
    )
    list_filter = ("is_active",)
    search_fields = ("email", "display_name")
    ordering = ("-created_at",)


@admin.register(domain.UserPreferences)
class UserPreferencesAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "user",
        "timezone",
        "locale",
        "preferred_strategy",
        "show_review_prompt",
    )
    search_fields = ("user__email", "timezone", "locale")


@admin.register(domain.AuthSession)
class AuthSessionAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "id",
        "user",
        "device_name",
        "created_at",
        "expires_at",
        "revoked_at",
    )
    list_filter = ("revocation_reason",)
    search_fields = ("user__email", "device_name")
    ordering = ("-created_at",)


@admin.register(domain.WorkType)
class WorkTypeAdmin(ReadOnlyTaskillerAdmin):
    list_display = ("display_name", "slug", "is_system", "owner", "version")
    list_filter = ("is_system", "cognitive_demand", "physicality", "learning_mode")
    search_fields = ("display_name", "slug", "owner__email")


@admin.register(domain.WorkItem)
class WorkItemAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "name",
        "kind",
        "status",
        "owner",
        "work_type",
        "priority",
        "created_at",
    )
    list_filter = ("kind", "status", "work_type")
    search_fields = ("name", "owner__email")
    ordering = ("-created_at",)


@admin.register(domain.FocusPlanRecommendation)
class FocusPlanRecommendationAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "id",
        "work_item",
        "strategy",
        "provenance",
        "engine_version",
        "created_at",
    )
    list_filter = ("strategy", "provenance", "engine_version")
    search_fields = ("work_item__name", "owner__email")
    ordering = ("-created_at",)


@admin.register(domain.FocusPlan)
class FocusPlanAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "name",
        "source",
        "is_template",
        "work_item",
        "owner",
        "version",
        "created_at",
    )
    list_filter = ("source", "is_template")
    search_fields = ("name", "work_item__name", "owner__email")
    ordering = ("-created_at",)


@admin.register(domain.FocusPlanSegment)
class FocusPlanSegmentAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "focus_plan",
        "segment_index",
        "kind",
        "duration_mode",
        "target_seconds",
        "optional",
    )
    list_filter = ("kind", "duration_mode", "optional")
    search_fields = ("focus_plan__name", "label")


@admin.register(domain.ExecutionSession)
class ExecutionSessionAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "id",
        "work_item",
        "state",
        "owner",
        "current_segment_index",
        "session_started_at",
        "ended_at",
    )
    list_filter = ("state",)
    search_fields = ("work_item__name", "owner__email")
    ordering = ("-session_started_at",)


@admin.register(domain.SessionEvent)
class SessionEventAdmin(ReadOnlyTaskillerAdmin):
    list_display = ("type", "session", "occurred_at", "segment_index", "owner")
    list_filter = ("type",)
    search_fields = ("session__id", "owner__email")
    ordering = ("-occurred_at",)


@admin.register(domain.SessionReview)
class SessionReviewAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "session",
        "owner",
        "focus_score",
        "fatigue_score",
        "difficulty_score",
        "satisfaction_score",
        "created_at",
    )
    search_fields = ("owner__email", "session__id")
    ordering = ("-created_at",)


@admin.register(domain.DataExportRequest)
class DataExportRequestAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "created_at",
        "completed_at",
        "expires_at",
    )
    list_filter = ("status",)
    search_fields = ("user__email",)
    ordering = ("-created_at",)


@admin.register(domain.AccountDeletionRequest)
class AccountDeletionRequestAdmin(ReadOnlyTaskillerAdmin):
    list_display = ("id", "user_id", "status", "requested_at", "execute_after")
    list_filter = ("status",)
    search_fields = ("user_id",)
    ordering = ("-requested_at",)


@admin.register(domain.OutboxJob)
class OutboxJobAdmin(ReadOnlyTaskillerAdmin):
    list_display = (
        "id",
        "job_type",
        "status",
        "attempts",
        "available_at",
        "completed_at",
    )
    list_filter = ("job_type", "status")
    ordering = ("-created_at",)


@admin.register(domain.SecurityEvent)
class SecurityEventAdmin(ReadOnlyTaskillerAdmin):
    list_display = ("event_type", "user_id", "created_at", "subject_hash")
    list_filter = ("event_type",)
    search_fields = ("user_id", "subject_hash")
    ordering = ("-created_at",)


# Intentionally not registered:
# - RefreshToken / verification / reset token tables (credential material)
# - IdempotencyRecord / RateLimitBucket (Django Admin doesn't support
#   CompositePrimaryKey models in Django 5.2)
