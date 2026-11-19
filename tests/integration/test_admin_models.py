"""Staff-console schema and immutable audit regressions for PostgreSQL CI."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from taskiller.django_domain import models as domain

pytestmark = pytest.mark.integration


@pytest.fixture
def enrollment():
    user = get_user_model().objects.create_user(
        username=f"operator-{uuid4()}", password="ci-only-individual-password", is_staff=True
    )
    return domain.StaffEnrollment.objects.create(user=user)


def audit_record(**kwargs):
    return domain.AdminAuditRecord.objects.create(action="account.suspend", **kwargs)


def test_staff_enrollment_is_unique_and_protects_identity(enrollment):
    with pytest.raises(IntegrityError), transaction.atomic():
        domain.StaffEnrollment.objects.create(user=enrollment.user)
    with pytest.raises(ProtectedError):
        enrollment.user.delete()
    assert enrollment.version == 1
    assert enrollment.last_totp_step == -1


@pytest.mark.parametrize(
    "model_name,field",
    [
        ("StaffChallenge", "secret_digest"),
        ("StaffSession", "token_digest"),
        ("StaffRecoveryCode", "code_digest"),
    ],
)
def test_staff_credentials_are_unique(enrollment, model_name, field):
    model = getattr(domain, model_name)
    values = {"enrollment": enrollment, field: "a" * 64}
    if model_name == "StaffSession":
        values.update(
            auth_hash="password-auth-hash", expires_at=timezone.now() + timedelta(hours=8)
        )
    if model_name == "StaffChallenge":
        values.update(purpose="login")
    model.objects.create(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(**values)


def test_command_receipt_identity_binds_actor_action_target_and_key(enrollment):
    values = {
        "actor_id": enrollment.id,
        "action": "account.suspend",
        "target_id": str(uuid4()),
        "key_digest": "a" * 64,
        "request_hash": "b" * 64,
        "response_json": {"status": 200},
    }
    domain.AdminCommandReceipt.objects.create(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        domain.AdminCommandReceipt.objects.create(**values)
    domain.AdminCommandReceipt.objects.create(**{**values, "target_id": str(uuid4())})
    domain.AdminCommandReceipt.objects.create(**{**values, "actor_id": uuid4()})


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
def test_audit_database_guard_covers_raw_sql_and_queryset(operation):
    record = audit_record()
    with pytest.raises(IntegrityError), transaction.atomic():
        if operation == "update":
            domain.AdminAuditRecord.objects.filter(pk=record.pk).update(comment="rewritten")
        elif operation == "delete":
            domain.AdminAuditRecord.objects.filter(pk=record.pk).delete()
        else:
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE admin_audit_records")
    record.refresh_from_db()
    assert record.comment == ""


def test_legacy_retention_flag_cannot_delete_audit():
    record = audit_record(created_at=timezone.now() - timedelta(days=400))
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL taskiller.retention = 'on'")
        record.delete()


def test_audit_retention_requires_explicit_cutoff_even_for_database_operator():
    record = audit_record(created_at=timezone.now() - timedelta(days=400))
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL taskiller.admin_audit_retention = 'on'")
        record.delete()


def test_audit_retention_operator_can_only_delete_older_rows():
    # CI uses an isolated PostgreSQL owner. Provisioning is rolled back with this test.
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if not cursor.fetchone()[0]:
            pytest.skip("Retention-role provisioning requires the disposable CI superuser")
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'taskiller_audit_retention'")
        if cursor.fetchone() is None:
            cursor.execute("CREATE ROLE taskiller_audit_retention NOLOGIN")
        cursor.execute("SET LOCAL taskiller.admin_audit_retention = 'on'")
        cursor.execute(
            "SELECT set_config('taskiller.admin_audit_retention_before', %s, true)",
            [(timezone.now() - timedelta(days=365)).isoformat()],
        )
    old = audit_record(created_at=timezone.now() - timedelta(days=400))
    recent = audit_record()
    old_id = old.id
    old.delete()
    assert not domain.AdminAuditRecord.objects.filter(pk=old_id).exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        recent.delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        domain.AdminAuditRecord.objects.filter(pk=recent.id).update(outcome="rewritten")


def test_audit_success_rolls_back_with_mutation():
    record_id = uuid4()
    with pytest.raises(RuntimeError), transaction.atomic():
        audit_record(id=record_id)
        raise RuntimeError("abort mutation")
    assert not domain.AdminAuditRecord.objects.filter(pk=record_id).exists()


def test_audit_identifiers_have_no_deletion_relationship(enrollment):
    record = audit_record(actor_id=str(enrollment.id), target_id=str(uuid4()))
    enrollment.delete()
    record.refresh_from_db()
    assert record.actor_id is not None
    assert not any(field.is_relation for field in domain.AdminAuditRecord._meta.fields)


def test_console_permissions_include_support_recovery():
    names = {name for name, _label in domain.StaffEnrollment._meta.permissions}
    assert names == {
        "console_view_users",
        "console_view_activity",
        "console_read_private",
        "console_manage_accounts",
        "console_manage_privacy",
        "console_retry_jobs",
        "console_manage_staff",
        "console_view_audit",
        "console_view_overview",
        "console_view_jobs",
        "console_recovery_email",
    }


def test_diagnostic_admin_only_exposes_allowlisted_metadata():
    forbidden = {
        "password_hash",
        "password",
        "mfa_secret_encrypted",
        "token_digest",
        "auth_hash",
        "code_digest",
        "secret_digest",
        "archive_bytes",
        "archive_sha256",
        "payload_json",
        "metadata_json",
        "last_error",
        "description",
        "notes",
        "changes_json",
        "suspension_reason",
    }
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label == "django_domain":
            assert model_admin.fields
            assert not forbidden.intersection(model_admin.get_readonly_fields(None))
    assert not admin.site.is_registered(get_user_model())
    assert not admin.site.is_registered(Group)
    for model in (domain.WorkType, domain.WorkItem, domain.FocusPlan):
        assert not admin.site.is_registered(model)


def test_suspension_is_distinct_from_deletion_state():
    now = timezone.now()
    user = domain.TaskillerUser.objects.create(
        id=uuid4(),
        email=f"suspended-{uuid4()}@example.test",
        password_hash="not-a-real-password-hash",
        password_changed_at=now,
        is_active=False,
        version=1,
        created_at=now,
        updated_at=now,
        suspended_at=now,
        suspension_reason="operator policy decision",
    )
    user.refresh_from_db()
    assert user.suspended_at == now
    assert user.suspension_reason == "operator policy decision"
    assert not domain.AccountDeletionRequest.objects.filter(user_id=user.id).exists()
    user.suspended_at = None
    user.suspension_reason = ""
    user.save(update_fields=["suspended_at", "suspension_reason"])
    user.refresh_from_db()
    assert not user.is_active
