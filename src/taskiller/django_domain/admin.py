from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import models

from taskiller.django_domain import models as domain


class ReadOnlyTaskillerAdmin(admin.ModelAdmin):
    """Allowlisted operational metadata without credentials or private payloads."""

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
        return self.fields or ()


@admin.register(domain.TaskillerUser)
class TaskillerUserAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "email",
        "display_name",
        "is_active",
        "email_verified_at",
        "suspended_at",
        "version",
        "created_at",
        "updated_at",
    )
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
    fields = (
        "user",
        "timezone",
        "locale",
        "preferred_strategy",
        "show_review_prompt",
        "version",
    )
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
    fields = (
        "id",
        "user",
        "device_name",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
        "revocation_reason",
    )
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
    fields = (
        "id",
        "slug",
        "is_system",
        "owner",
        "version",
        "created_at",
        "updated_at",
    )
    list_display = ("id", "slug", "is_system", "owner", "version")
    list_filter = ("is_system", "cognitive_demand", "physicality", "learning_mode")
    search_fields = ("slug", "owner__email")


@admin.register(domain.WorkItem)
class WorkItemAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "kind",
        "status",
        "owner",
        "priority",
        "version",
        "created_at",
        "updated_at",
    )
    list_display = (
        "id",
        "kind",
        "status",
        "owner",
        "priority",
        "created_at",
    )
    list_filter = ("kind", "status")
    search_fields = ("owner__email",)
    ordering = ("-created_at",)


@admin.register(domain.FocusPlanRecommendation)
class FocusPlanRecommendationAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "owner",
        "strategy",
        "provenance",
        "engine_version",
        "created_at",
    )
    list_display = (
        "id",
        "strategy",
        "provenance",
        "engine_version",
        "created_at",
    )
    list_filter = ("strategy", "provenance", "engine_version")
    search_fields = ("owner__email",)
    ordering = ("-created_at",)


@admin.register(domain.FocusPlan)
class FocusPlanAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "owner",
        "source",
        "is_template",
        "version",
        "created_at",
        "updated_at",
    )
    list_display = (
        "id",
        "source",
        "is_template",
        "owner",
        "version",
        "created_at",
    )
    list_filter = ("source", "is_template")
    search_fields = ("owner__email",)
    ordering = ("-created_at",)


@admin.register(domain.FocusPlanSegment)
class FocusPlanSegmentAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "segment_index",
        "kind",
        "duration_mode",
        "target_seconds",
        "optional",
    )
    list_display = (
        "segment_index",
        "kind",
        "duration_mode",
        "target_seconds",
        "optional",
    )
    list_filter = ("kind", "duration_mode", "optional")
    search_fields = ("id",)


@admin.register(domain.ExecutionSession)
class ExecutionSessionAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "owner",
        "state",
        "current_segment_index",
        "session_started_at",
        "ended_at",
    )
    list_display = (
        "id",
        "state",
        "owner",
        "current_segment_index",
        "session_started_at",
        "ended_at",
    )
    list_filter = ("state",)
    search_fields = ("owner__email",)
    ordering = ("-session_started_at",)


@admin.register(domain.SessionEvent)
class SessionEventAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "type",
        "occurred_at",
        "segment_index",
        "owner",
    )
    list_display = ("type", "id", "occurred_at", "segment_index", "owner")
    list_filter = ("type",)
    search_fields = ("session__id", "owner__email")
    ordering = ("-occurred_at",)


@admin.register(domain.SessionReview)
class SessionReviewAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "owner",
        "focus_score",
        "fatigue_score",
        "difficulty_score",
        "satisfaction_score",
        "created_at",
    )
    list_display = (
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
    fields = (
        "id",
        "user",
        "status",
        "created_at",
        "completed_at",
        "expires_at",
    )
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
    fields = (
        "id",
        "user_id",
        "status",
        "requested_at",
        "execute_after",
    )
    list_display = ("id", "user_id", "status", "requested_at", "execute_after")
    list_filter = ("status",)
    search_fields = ("user_id",)
    ordering = ("-requested_at",)


@admin.register(domain.OutboxJob)
class OutboxJobAdmin(ReadOnlyTaskillerAdmin):
    fields = (
        "id",
        "job_type",
        "status",
        "attempts",
        "available_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
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
    fields = (
        "id",
        "event_type",
        "user_id",
        "created_at",
    )
    list_display = ("event_type", "user_id", "created_at")
    list_filter = ("event_type",)
    search_fields = ("user_id",)
    ordering = ("-created_at",)


# Intentionally not registered:
# - RefreshToken / verification / reset token tables (credential material)
# - IdempotencyRecord / RateLimitBucket (Django Admin doesn't support
#   CompositePrimaryKey models in Django 5.2)


# The console owns staff authorization; the diagnostic admin must not expose
# password hashes or bypass the audited Owner/last-Owner workflows via auth forms.
for authentication_model in (get_user_model(), Group):
    if admin.site.is_registered(authentication_model):
        admin.site.unregister(authentication_model)


# Django's object headings and breadcrumbs call __str__ even with safe fields.
# These models expose private work names there; inspect them through audited
# console projections instead of the diagnostic site.
for private_content_model in (domain.WorkType, domain.WorkItem, domain.FocusPlan):
    if admin.site.is_registered(private_content_model):
        admin.site.unregister(private_content_model)
