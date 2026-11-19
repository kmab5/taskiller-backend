from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection

from taskiller.core.time import utc_now
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_domain.models import StaffEnrollment

GROUP_PREFIX = "taskiller-console:"
CAPABILITIES = frozenset(
    {
        "view_users",
        "view_activity",
        "read_private",
        "manage_accounts",
        "manage_privacy",
        "retry_jobs",
        "manage_staff",
        "view_audit",
        "view_overview",
        "view_jobs",
        "recovery_email",
    }
)
ROLE_CAPABILITIES = {
    "Owner": CAPABILITIES,
    "Administrator": CAPABILITIES - {"manage_staff", "read_private", "manage_privacy"},
    "Support": frozenset({"view_users", "view_activity", "recovery_email"}),
    "Analyst": frozenset({"view_overview"}),
}
OWNER_LOCK_ID = 742301901


def ensure_roles():
    content_type = ContentType.objects.get_for_model(StaffEnrollment)
    permissions = {}
    for capability in CAPABILITIES:
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=f"console_{capability}",
            defaults={"name": f"Console: {capability}"},
        )
        permissions[capability] = permission
    for role, capabilities in ROLE_CAPABILITIES.items():
        group, _ = Group.objects.get_or_create(name=f"{GROUP_PREFIX}{role}")
        group.permissions.set([permissions[name] for name in capabilities])


def effective_capabilities(user):
    # Do not call has_perm/get_all_permissions: Django superusers implicitly pass
    # those checks. Only dedicated role groups and explicit named grants count.
    group_codes = Permission.objects.filter(
        group__user=user,
        group__name__startswith=GROUP_PREFIX,
        content_type__app_label="django_domain",
        content_type__model="staffenrollment",
    ).values_list("codename", flat=True)
    direct_codes = user.user_permissions.filter(
        content_type__app_label="django_domain",
        content_type__model="staffenrollment",
        codename__in=["console_read_private", "console_manage_privacy"],
    ).values_list("codename", flat=True)
    return sorted(
        {code.removeprefix("console_") for code in [*group_codes, *direct_codes]} & CAPABILITIES
    )


@contextmanager
def owner_lock():
    # Call only within transaction.atomic, including operator commands.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [OWNER_LOCK_ID])
    yield


def ensure_not_last_owner(enrollment):
    owners = (
        StaffEnrollment.objects.filter(
            enabled=True,
            user__is_active=True,
            user__is_staff=True,
            user__groups__name=f"{GROUP_PREFIX}Owner",
        )
        .exclude(mfa_secret_encrypted="")
        .distinct()
    )
    if owners.filter(id=enrollment.id).exists() and owners.count() <= 1:
        raise TaskillerAPIError(409, "admin_last_owner", "The last Owner cannot lose access")


def require_capability(request, action, step_up=False, target=None):
    del target
    session = request.auth
    if session is None or not getattr(request.user, "is_authenticated", False):
        raise TaskillerAPIError(401, "admin_auth_required", "Staff authentication required")
    enrollment = (
        StaffEnrollment.objects.select_related("user")
        .filter(
            id=session.enrollment_id,
            enabled=True,
            user__is_active=True,
            user__is_staff=True,
        )
        .first()
    )
    if enrollment is None or session.revoked_at or session.expires_at <= utc_now():
        raise TaskillerAPIError(401, "admin_auth_required", "Staff session is no longer valid")
    if action and action not in effective_capabilities(enrollment.user):
        raise TaskillerAPIError(403, "admin_permission_denied", "Staff capability required")
    if step_up and session.mfa_verified_at < utc_now() - timedelta(minutes=5):
        raise TaskillerAPIError(403, "admin_step_up_required", "Fresh MFA verification required")
    return enrollment
