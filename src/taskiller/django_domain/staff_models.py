"""Dedicated staff-console state; no product credentials or audit foreign keys."""

from typing import ClassVar
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone

from taskiller.django_domain.models import PsycopgCompatibleJSONField


class StaffEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="console_enrollment"
    )
    enabled = models.BooleanField(default=True)
    mfa_secret_encrypted = models.TextField(default="", blank=True)
    last_totp_step = models.BigIntegerField(default=-1)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "staff_enrollments"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["-created_at", "-id"], name="tk_admin_staff_cursor"),
        ]
        permissions: ClassVar[list[tuple[str, str]]] = [
            ("console_view_users", "Console: view users"),
            ("console_view_activity", "Console: view activity"),
            ("console_read_private", "Console: read private"),
            ("console_manage_accounts", "Console: manage accounts"),
            ("console_manage_privacy", "Console: manage privacy"),
            ("console_retry_jobs", "Console: retry jobs"),
            ("console_manage_staff", "Console: manage staff"),
            ("console_view_audit", "Console: view audit"),
            ("console_view_overview", "Console: view overview"),
            ("console_view_jobs", "Console: view jobs"),
            ("console_recovery_email", "Console: recovery email"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="tk_staff_enrollment_version"
            ),
            models.CheckConstraint(
                condition=models.Q(last_totp_step__gte=-1), name="tk_staff_totp_step"
            ),
        ]


class StaffChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    enrollment = models.ForeignKey(
        "django_domain.StaffEnrollment",
        null=True,
        on_delete=models.CASCADE,
        related_name="challenges",
    )
    secret_digest = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=40)
    expires_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    payload_json = PsycopgCompatibleJSONField(default=dict)

    class Meta:
        db_table = "staff_challenges"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_staff_challenge_expiry"),
        ]


class StaffSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    enrollment = models.ForeignKey(
        "django_domain.StaffEnrollment", on_delete=models.CASCADE, related_name="sessions"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    auth_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=timezone.now)
    mfa_verified_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "staff_sessions"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at"], name="tk_staff_session_expiry"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="tk_staff_session_version"
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gte=models.F("created_at")),
                name="tk_staff_session_lifetime",
            ),
        ]


class StaffRecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    enrollment = models.ForeignKey(
        "django_domain.StaffEnrollment", on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_digest = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "staff_recovery_codes"


class AdminAuditRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    actor_id = models.CharField(max_length=128, null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=80, default="", blank=True)
    target_id = models.CharField(max_length=128, default="", blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    request_id = models.CharField(max_length=128, default="", blank=True)
    outcome = models.CharField(max_length=40, default="success")
    reason_code = models.CharField(max_length=80, default="", blank=True)
    comment = models.TextField(default="", blank=True)
    changes_json = PsycopgCompatibleJSONField(default=dict)

    class Meta:
        db_table = "admin_audit_records"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["-created_at", "-id"], name="tk_admin_audit_cursor"),
            models.Index(fields=["actor_id", "-created_at", "-id"], name="tk_admin_audit_actor"),
            models.Index(
                fields=["target_type", "target_id", "-created_at", "-id"],
                name="tk_admin_audit_target",
            ),
        ]


class AdminCommandReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    actor_id = models.UUIDField()
    action = models.CharField(max_length=100)
    target_id = models.CharField(max_length=128, default="", blank=True)
    key_digest = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    response_json = PsycopgCompatibleJSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "admin_command_receipts"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["created_at"], name="tk_admin_receipt_retention"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["actor_id", "action", "target_id", "key_digest"],
                name="tk_admin_receipt_identity",
            ),
        ]
