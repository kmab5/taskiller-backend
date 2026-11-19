"""One-time, audited enrollment/recovery of a named operator identity."""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taskiller.core.time import utc_now
from taskiller.django_api.admin_api.audit import record
from taskiller.django_api.admin_api.authentication import digest
from taskiller.django_api.admin_api.permissions import GROUP_PREFIX, ensure_roles, owner_lock
from taskiller.django_domain.models import (
    StaffChallenge,
    StaffEnrollment,
    StaffRecoveryCode,
    StaffSession,
)


class Command(BaseCommand):
    help = (
        "Enroll a named Django staff user as console Owner or recover lost MFA. "
        "Outputs one single-use invitation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--recover-mfa", action="store_true")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        del args
        reason = options["reason"].strip()
        if not reason or len(reason) > 500:
            raise CommandError("Provide an operator reason of 1-500 characters")
        User = get_user_model()
        with transaction.atomic(), owner_lock():
            user = (
                User.objects.select_for_update()
                .filter(**{User.USERNAME_FIELD: options["username"]})
                .first()
            )
            if user is None or not user.is_staff or not user.is_active:
                raise CommandError("The named Django identity must already be active staff")
            ensure_roles()
            enrollment, created = StaffEnrollment.objects.get_or_create(user=user)
            enrollment = StaffEnrollment.objects.select_for_update().get(id=enrollment.id)
            if not created and enrollment.mfa_secret_encrypted and not options["recover_mfa"]:
                raise CommandError("Already enrolled; recovery requires --recover-mfa and a reason")
            now = utc_now()
            user.groups.add(Group.objects.get(name=f"{GROUP_PREFIX}Owner"))
            enrollment.enabled = True
            enrollment.mfa_secret_encrypted = ""
            enrollment.last_totp_step = -1
            enrollment.version += 1
            enrollment.updated_at = now
            enrollment.save()
            StaffSession.objects.filter(enrollment=enrollment, revoked_at__isnull=True).update(
                revoked_at=now
            )
            StaffRecoveryCode.objects.filter(enrollment=enrollment, used_at__isnull=True).update(
                used_at=now
            )
            StaffChallenge.objects.filter(enrollment=enrollment, consumed_at__isnull=True).update(
                consumed_at=now
            )
            token = secrets.token_urlsafe(48)
            invitation = StaffChallenge.objects.create(
                enrollment=enrollment,
                purpose="enrollment",
                secret_digest=digest(token),
                expires_at=now + timedelta(hours=1),
                payload_json={},
            )
            record(
                None,
                "operator.mfa_recovery" if options["recover_mfa"] else "operator.bootstrap_owner",
                target_type="staff",
                target_id=enrollment.id,
                reason={"reasonCode": "operator_cli", "comment": reason},
                changes={"roles": ["Owner"], "version": enrollment.version},
            )
        self.stdout.write(
            f"Single-use enrollment token (expires {invitation.expires_at.isoformat()}):"
        )
        self.stdout.write(token)
