from __future__ import annotations

from collections.abc import Mapping

from django.shortcuts import get_object_or_404
from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from taskiller.django_api.admin_api import audit
from taskiller.django_api.admin_api import queries as q
from taskiller.django_api.admin_api import read_serializers as s
from taskiller.django_api.admin_api.authentication import AdminAPIView
from taskiller.django_api.admin_api.permissions import (
    ROLE_CAPABILITIES,
    effective_capabilities,
    require_capability,
)
from taskiller.django_domain import models as m
from taskiller.users.etag import make_etag


def filters(request, serializer=s.ReadFiltersSerializer, *, body=False):
    source = request.data if body else request.query_params
    if not isinstance(source, Mapping):
        raise ValidationError("Expected a filter object.")
    data = source.copy()
    if hasattr(data, "getlist") and any(len(data.getlist(k)) != 1 for k in data):
        raise ValidationError("Repeated filters are not allowed.")
    if data.get("cursor"):
        if not isinstance(data["cursor"], str) or len(data["cursor"]) > 2048:
            raise ValidationError({"cursor": "Invalid cursor."})
        cursor = q.decode_cursor(data["cursor"])
        if cursor["start"] is not None:
            data.setdefault("start", cursor["start"])
        data.setdefault("end", cursor["end"])
    parsed = serializer(data=data)
    parsed.is_valid(raise_exception=True)
    return parsed.validated_data


def scope(request, stream):
    capabilities = ",".join(sorted(effective_capabilities(request.user)))
    return f"{request.user.pk}:{capabilities}:{stream}"


def respond(serializer, data):
    response = Response(serializer(data).data)
    response["Cache-Control"] = "no-store"
    return response


def account(user_id):
    return get_object_or_404(q.users_queryset(), pk=user_id)


class OverviewView(AdminAPIView):
    capability = "view_overview"

    @extend_schema(
        operation_id="adminOverview",
        parameters=[s.ReadFiltersSerializer],
        responses=s.OverviewSerializer,
    )
    def get(self, request):
        capabilities = effective_capabilities(request.user)
        return respond(
            s.OverviewSerializer,
            q.overview(
                filters(request),
                "view_jobs" in capabilities,
                include_privacy="manage_privacy" in capabilities,
            ),
        )


class UsersView(AdminAPIView):
    capability = "view_users"

    @extend_schema(
        operation_id="adminUsers",
        parameters=[s.UserFiltersSerializer],
        responses=s.UserPageSerializer,
    )
    def get(self, request):
        return respond(
            s.UserPageSerializer,
            q.users(filters(request, s.UserFiltersSerializer), scope(request, "users")),
        )


class UserSearchView(AdminAPIView):
    capability = "view_users"

    @extend_schema(
        operation_id="adminSearchUsers",
        request=s.UserFiltersSerializer,
        responses=s.UserPageSerializer,
    )
    def post(self, request):
        # AdminAPIView enforces CSRF for this cookie-authenticated POST as for commands.
        return respond(
            s.UserPageSerializer,
            q.users(filters(request, s.UserFiltersSerializer, body=True), scope(request, "users")),
        )


class UserDetailView(AdminAPIView):
    capability = "view_users"

    @extend_schema(operation_id="adminUserDetail", responses=s.UserSerializer)
    def get(self, request, user_id):
        row = account(user_id)
        response = respond(s.UserSerializer, q.user_projection(row))
        response["ETag"] = make_etag("user", row.id, row.version)
        return response


class UserActivityView(AdminAPIView):
    capability = "view_activity"

    @extend_schema(
        operation_id="adminUserActivity",
        parameters=[s.ReadFiltersSerializer],
        responses=s.ActivityPageSerializer,
    )
    def get(self, request, user_id):
        account(user_id)
        security = "manage_accounts" in effective_capabilities(request.user)
        return respond(
            s.ActivityPageSerializer,
            q.activity(
                filters(request),
                scope(request, f"activity:{user_id}:{security}"),
                user_id,
                security,
            ),
        )


class UserSessionsView(AdminAPIView):
    capability = "view_users"

    @extend_schema(
        operation_id="adminUserSessions",
        parameters=[s.ReadFiltersSerializer],
        responses=s.SessionPageSerializer,
    )
    def get(self, request, user_id):
        account(user_id)
        values = filters(request)
        rows = q.bounded(m.AuthSession.objects.filter(user_id=user_id), values).only(
            "id", "device_name", "created_at", "last_used_at", "expires_at", "revoked_at"
        )
        return respond(
            s.SessionPageSerializer,
            q.page(rows, values, scope(request, f"sessions:{user_id}"), q.session_projection),
        )


class JobsView(AdminAPIView):
    capability = "view_jobs"

    @extend_schema(
        operation_id="adminJobs", parameters=[s.JobFiltersSerializer], responses=s.JobPageSerializer
    )
    def get(self, request):
        values = filters(request, s.JobFiltersSerializer)
        capabilities = effective_capabilities(request.user)
        include_privacy = "manage_privacy" in capabilities
        if include_privacy:
            require_capability(request, "manage_privacy", step_up=True)
        result = q.jobs(
            values,
            scope(request, f"jobs:{include_privacy}"),
            include_privacy=include_privacy,
            retry="retry_jobs" in capabilities,
        )
        if include_privacy:
            audit.record(request, "privacy.jobs", target_type="privacy_request")
        return respond(s.JobPageSerializer, result)


class PrivacyRequestsView(AdminAPIView):
    capability = "manage_privacy"
    step_up = True

    @extend_schema(
        operation_id="adminPrivacyRequests",
        parameters=[s.PrivacyFiltersSerializer],
        responses=s.PrivacyPageSerializer,
    )
    def get(self, request):
        values = filters(request, s.PrivacyFiltersSerializer)
        kind = values["type"]
        rows, field = q.privacy_queryset(kind, values)
        result = q.page(
            rows,
            values,
            scope(request, f"privacy:{kind}"),
            lambda row: q.privacy_projection(row, kind),
            field,
        )
        audit.record(request, "privacy.list", target_type="privacy_request")
        return respond(s.PrivacyPageSerializer, result)


class PrivacyDetailView(AdminAPIView):
    capability = "manage_privacy"
    step_up = True

    @extend_schema(
        operation_id="adminPrivacyDetail",
        parameters=[s.PrivacyFiltersSerializer],
        responses=s.PrivacySerializer,
    )
    def get(self, request, request_id):
        values = filters(request, s.PrivacyFiltersSerializer)
        rows, _ = q.privacy_queryset(values["type"], values)
        row = get_object_or_404(rows, pk=request_id)
        audit.record(request, "privacy.read", target_type=values["type"], target_id=str(row.id))
        return respond(s.PrivacySerializer, q.privacy_projection(row, values["type"]))


class AuditView(AdminAPIView):
    capability = "view_audit"

    @extend_schema(
        operation_id="adminAudit",
        parameters=[s.AuditFiltersSerializer],
        responses=s.AuditPageSerializer,
    )
    def get(self, request):
        values = filters(request, s.AuditFiltersSerializer)
        owner = request.user.groups.filter(name="taskiller-console:Owner").exists()
        rows = q.bounded(q.scoped_audit(owner), values)
        for key, field in (
            ("actor", "actor_id"),
            ("target", "target_id"),
            ("action", "action"),
            ("outcome", "outcome"),
        ):
            if key in values:
                rows = rows.filter(**{field: values[key]})
        return respond(
            s.AuditPageSerializer,
            q.page(
                rows,
                values,
                scope(request, f"audit:{owner}"),
                lambda row: q.audit_projection(row, owner=owner),
            ),
        )


class StaffView(AdminAPIView):
    capability = "manage_staff"
    step_up = True

    @extend_schema(
        operation_id="adminStaff",
        parameters=[s.ReadFiltersSerializer],
        responses=s.StaffPageSerializer,
    )
    def get(self, request):
        values = filters(request)
        rows = q.bounded(
            m.StaffEnrollment.objects.select_related("user").prefetch_related(
                "user__groups", "user__user_permissions"
            ),
            values,
        )

        def project(row):
            return {
                "id": row.id,
                "userId": str(row.user_id),
                "displayName": row.user.get_full_name() or row.user.get_username(),
                "enabled": row.enabled,
                "mfaEnrolled": bool(row.mfa_secret_encrypted),
                "roles": sorted(
                    g.name.removeprefix("taskiller-console:")
                    for g in row.user.groups.all()
                    if g.name.startswith("taskiller-console:")
                ),
                "capabilities": sorted(effective_capabilities(row.user)),
                "createdAt": row.created_at,
                "version": row.version,
                # PATCH staff/{id}/roles uses this exact If-Match value.
                "etag": make_etag("staff", row.id, row.version),
            }

        return respond(
            s.StaffPageSerializer, q.page(rows, values, scope(request, "staff"), project)
        )


class RolesView(AdminAPIView):
    capability = "manage_staff"
    step_up = True

    @extend_schema(operation_id="adminRoles", responses=s.RoleSerializer(many=True))
    def get(self, request):
        response = Response(
            s.RoleSerializer(
                [
                    {"name": name, "version": 1, "capabilities": sorted(capabilities)}
                    for name, capabilities in ROLE_CAPABILITIES.items()
                ],
                many=True,
            ).data
        )
        response["Cache-Control"] = "no-store"
        return response


class UserWorkView(AdminAPIView):
    capability = "read_private"
    step_up = True

    @extend_schema(
        operation_id="adminUserWork",
        parameters=[s.WorkFiltersSerializer],
        responses=s.WorkPageSerializer,
    )
    def get(self, request, user_id):
        account(user_id)
        values = filters(request, s.WorkFiltersSerializer)
        kind = values["kind"]
        rows = q.bounded(q.work_queryset(kind, user_id), values)
        result = q.page(
            rows,
            values,
            scope(request, f"work:{user_id}:{kind}"),
            lambda row: q.work_projection(row, kind),
        )
        audit.record(request, "work.list", target_type="user", target_id=str(user_id))
        return respond(s.WorkPageSerializer, result)


class WorkDetailView(AdminAPIView):
    capability = "read_private"
    step_up = True

    @extend_schema(
        operation_id="adminWorkDetail",
        parameters=[s.WorkFiltersSerializer],
        responses=s.WorkSerializer,
    )
    def get(self, request, work_id):
        values = filters(request, s.WorkFiltersSerializer)
        kind = values["kind"]
        row = get_object_or_404(q.work_queryset(kind, detail=True), pk=work_id)
        audit.record(request, "work.read", target_type=kind, target_id=str(row.id))
        response = respond(s.WorkSerializer, q.work_projection(row, kind, detail=True))
        response["ETag"] = make_etag(q.WORK_ETAG_KINDS[kind], row.id, row.version)
        return response


urlpatterns = [
    path("overview", OverviewView.as_view(), name="admin-overview"),
    path("users", UsersView.as_view(), name="admin-users"),
    path("users/search", UserSearchView.as_view(), name="admin-users-search"),
    path("users/<uuid:user_id>", UserDetailView.as_view(), name="admin-user-detail"),
    path("users/<uuid:user_id>/activity", UserActivityView.as_view(), name="admin-user-activity"),
    path("users/<uuid:user_id>/sessions", UserSessionsView.as_view(), name="admin-user-sessions"),
    path("jobs", JobsView.as_view(), name="admin-jobs"),
    path("privacy/requests", PrivacyRequestsView.as_view(), name="admin-privacy-requests"),
    path(
        "privacy/requests/<uuid:request_id>",
        PrivacyDetailView.as_view(),
        name="admin-privacy-detail",
    ),
    path("audit", AuditView.as_view(), name="admin-audit"),
    path("staff", StaffView.as_view(), name="admin-staff"),
    path("roles", RolesView.as_view(), name="admin-roles"),
    path("users/<uuid:user_id>/work", UserWorkView.as_view(), name="admin-user-work"),
    path("work/<uuid:work_id>", WorkDetailView.as_view(), name="admin-work-detail"),
]
