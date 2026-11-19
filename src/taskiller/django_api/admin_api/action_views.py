"""Relative URL patterns for console commands; mounted by admin_api.urls."""

from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from taskiller.django_api.admin_api import actions
from taskiller.django_api.admin_api.action_serializers import (
    AccountCommandSerializer,
    BulkCommandSerializer,
    BulkResponseSerializer,
    CommandResponseSerializer,
    CommandSerializer,
    InvitationSerializer,
    RolesSerializer,
    WorkCorrectionSerializer,
)
from taskiller.django_api.admin_api.authentication import AdminAPIView


def _validated(serializer_type, request):
    serializer = serializer_type(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _response(result):
    response = Response(
        result, status=202 if result.get("status") in {"queued", "scheduled"} else 200
    )
    response["Cache-Control"] = "no-store"
    if "etag" in result:
        response["ETag"] = result["etag"]
    return response


class CommandView(AdminAPIView):
    writes = True
    serializer_type = CommandSerializer
    command = ""
    capability = "manage_accounts"
    step_up = False

    @extend_schema(request=CommandSerializer, responses={200: CommandResponseSerializer})
    def post(self, request, target_id=None):
        data = _validated(self.serializer_type, request)
        return _response(
            actions.execute(
                request,
                self.command,
                target_id if target_id is not None else "invitations",
                data,
                key=request.headers.get("Idempotency-Key"),
                if_match=request.headers.get("If-Match"),
            )
        )


class AccountCommandView(CommandView):
    serializer_type = AccountCommandSerializer

    @extend_schema(request=AccountCommandSerializer, responses={200: CommandResponseSerializer})
    def post(self, request, target_id):
        return super().post(request, target_id)


class SuspendView(AccountCommandView):
    command = "users.suspend"
    step_up = True


class ReactivateView(AccountCommandView):
    command = "users.reactivate"
    step_up = True


class RecoveryEmailView(AccountCommandView):
    command = "users.recovery-email"
    capability = "recovery_email"


class RevokeSessionsView(AccountCommandView):
    command = "users.revoke-sessions"


class RetryJobView(CommandView):
    command = "jobs.retry"
    capability = "retry_jobs"


class StaffInvitationView(CommandView):
    command = "staff.invite"
    capability = "manage_staff"
    step_up = True
    serializer_type = InvitationSerializer

    @extend_schema(request=InvitationSerializer, responses={200: CommandResponseSerializer})
    def post(self, request):
        return super().post(request)


class StaffRolesView(CommandView):
    command = "staff.roles"
    capability = "manage_staff"
    step_up = True
    serializer_type = RolesSerializer
    http_method_names = ["patch", "options"]

    @extend_schema(request=RolesSerializer, responses={200: CommandResponseSerializer})
    def patch(self, request, target_id):
        return super().post(request, target_id)


class StaffRevokeAccessView(CommandView):
    command = "staff.revoke-access"
    capability = "manage_staff"
    step_up = True


class PrivacyExportView(CommandView):
    command = "privacy.export"
    capability = "manage_privacy"
    step_up = True


class PrivacyDeletionView(PrivacyExportView):
    command = "privacy.deletion"


class WorkCorrectionView(CommandView):
    command = "work.correct"
    capability = "read_private"
    step_up = True
    serializer_type = WorkCorrectionSerializer

    @extend_schema(request=WorkCorrectionSerializer, responses={200: CommandResponseSerializer})
    def post(self, request, target_id):
        return super().post(request, target_id)


class BulkPreviewView(AdminAPIView):
    writes = True
    capability = ""

    @extend_schema(request=BulkCommandSerializer, responses={200: BulkResponseSerializer})
    def post(self, request):
        result = actions.bulk_preview(request, _validated(BulkCommandSerializer, request))
        return _response(result)


class BulkExecuteView(AdminAPIView):
    writes = True
    capability = ""

    @extend_schema(request=BulkCommandSerializer, responses={200: BulkResponseSerializer})
    def post(self, request):
        result = actions.bulk_execute(
            request,
            _validated(BulkCommandSerializer, request),
            key=request.headers.get("Idempotency-Key"),
        )
        return _response(result)


urlpatterns = [
    path("users/<uuid:target_id>/suspend", SuspendView.as_view()),
    path("users/<uuid:target_id>/reactivate", ReactivateView.as_view()),
    path("users/<uuid:target_id>/recovery-email", RecoveryEmailView.as_view()),
    path("users/<uuid:target_id>/revoke-sessions", RevokeSessionsView.as_view()),
    path("jobs/<uuid:target_id>/retry", RetryJobView.as_view()),
    path("staff/invitations", StaffInvitationView.as_view()),
    path("staff/<uuid:target_id>/roles", StaffRolesView.as_view()),
    path("staff/<uuid:target_id>/revoke-access", StaffRevokeAccessView.as_view()),
    path("users/<uuid:target_id>/privacy/export", PrivacyExportView.as_view()),
    path("users/<uuid:target_id>/privacy/deletion", PrivacyDeletionView.as_view()),
    path("work/<uuid:target_id>/correct", WorkCorrectionView.as_view()),
    path("bulk/preview", BulkPreviewView.as_view()),
    path("bulk/execute", BulkExecuteView.as_view()),
]
