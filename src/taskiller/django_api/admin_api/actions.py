"""Transactional console commands.

Suspension revokes product authentication only. Already-running Execution Sessions
remain running; staff must use an explicit domain event to change execution state.
No command rewrites historical execution events or exposes export credentials.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import nullcontext
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from taskiller.django_api.admin_api.action_serializers import (
    AccountCommandSerializer,
    CommandSerializer,
    RolesSerializer,
    WorkCorrectionSerializer,
)
from taskiller.django_api.admin_api.audit import record
from taskiller.django_api.admin_api.authentication import auth_hash
from taskiller.django_api.admin_api.permissions import (
    ensure_not_last_owner,
    owner_lock,
    require_capability,
)
from taskiller.django_api.auth_service import DjangoAuthService
from taskiller.django_api.errors import TaskillerAPIError
from taskiller.django_api.privacy_service import request_data_export, schedule_account_deletion
from taskiller.django_api.work_service import (
    DjangoWorkService,
    require_etag,
    require_idempotency_key,
    validate_payload,
)
from taskiller.django_domain.models import (
    AccountDeletionRequest,
    AdminCommandReceipt,
    AuthSession,
    DataExportRequest,
    ExecutionSession,
    FocusPlan,
    OutboxJob,
    StaffChallenge,
    StaffEnrollment,
    StaffSession,
    TaskillerUser,
    WorkItem,
    WorkType,
)
from taskiller.users.etag import make_etag

GROUP_PREFIX = "taskiller-console:"
# Email and deletion retries are deliberately excluded: delivery can have succeeded
# before acknowledgement, and deletion needs operator diagnosis, not blind replay.
RETRYABLE_JOB_TYPES = frozenset({"data_export"})
ACCOUNT_ACTIONS = frozenset({"suspend", "reactivate", "recovery-email", "revoke-sessions"})
STAFF_ACTIONS = frozenset({"invite", "roles", "revoke-access"})
BULK_ACTIONS = ACCOUNT_ACTIONS | {
    "staff.roles",
    "staff.revoke-access",
    "jobs.retry",
    "privacy.export",
    "privacy.deletion",
    "work.correct",
}


def _error(status, code, title):
    return TaskillerAPIError(status, code, title)


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True))


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _get(query, **filters):
    row = query.filter(**filters).first()
    if row is None:
        raise _error(404, "not_found", "Resource not found")
    return row


def _policy(request, action, target):
    if action.startswith("staff."):
        capability, step_up = "manage_staff", True
    elif action == "jobs.retry":
        capability, step_up = "retry_jobs", False
    elif action.startswith("privacy."):
        capability, step_up = "manage_privacy", True
    elif action == "work.correct":
        capability, step_up = "read_private", True
        require_capability(request, "manage_accounts", target=target)
    elif action == "users.recovery-email":
        capability, step_up = "recovery_email", False
    else:
        capability, step_up = "manage_accounts", action in {"users.suspend", "users.reactivate"}
    require_capability(request, capability, step_up=step_up, target=target)


def _lock_actor(request):
    """Serialize actor receipts and recheck live identity/session after acquiring locks."""
    actor = _get(StaffEnrollment.objects.select_for_update(), id=request.auth.enrollment_id)
    user = get_user_model().objects.select_for_update().get(pk=actor.user_id)
    actor.user = user
    session = _get(StaffSession.objects.select_for_update(), id=request.auth.id)
    now = timezone.now()
    if (
        not actor.enabled
        or not actor.mfa_secret_encrypted
        or not user.is_active
        or not user.is_staff
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.enrollment_id != actor.id
        or session.last_seen_at <= now - timedelta(minutes=30)
        or not constant_time_compare(session.auth_hash, auth_hash(actor))
    ):
        raise _error(401, "staff_session_invalid", "Staff authentication required")
    request.user = user
    request.auth = session
    return actor


def _receipt(request, actor, action, target, data, key, if_match):
    request_hash = _digest(
        json.dumps(
            _json({"payload": data, "ifMatch": if_match}), sort_keys=True, separators=(",", ":")
        )
    )
    key_digest = _digest(key)
    prior = AdminCommandReceipt.objects.filter(
        actor_id=actor.id, action=action, target_id=str(target), key_digest=key_digest
    ).first()
    if prior is not None:
        if prior.request_hash != request_hash:
            raise _error(409, "idempotency_conflict", "Idempotency key payload mismatch")
        _policy(request, action, target)
        return prior, request_hash, key_digest
    return None, request_hash, key_digest


def execute(request, action, target, data, *, key, if_match=None):
    """Authorize replay too; success audit and receipt commit with the mutation."""
    try:
        if not getattr(settings, "ADMIN_CONSOLE_WRITES_ENABLED", False):
            raise _error(403, "admin_writes_disabled", "Administrative writes are disabled")
        key = require_idempotency_key(key)
        if not isinstance(data.get("reason"), dict) or not data["reason"].get("reasonCode"):
            raise _error(422, "reason_required", "A reason is required")
        _policy(request, action, target)
        with transaction.atomic(), owner_lock() if action.startswith("staff.") else nullcontext():
            actor = _lock_actor(request)
            _policy(request, action, target)
            if action == "jobs.retry":
                _job_policy(request, _get(OutboxJob.objects.select_for_update(), id=target))
            prior, request_hash, key_digest = _receipt(
                request, actor, action, target, data, key, if_match
            )
            if prior is not None:
                if action == "staff.invite":
                    return {
                        "status": prior.response_json["status"],
                        "invitationId": prior.response_json["invitationId"],
                        "replayed": True,
                        "detail": "Invitation tokens are shown once. Issue a new invitation "
                        "if the token was lost.",
                    }
                return {**prior.response_json, "replayed": True}
            service_key = _digest(f"{actor.id}:{action}:{target}:{key_digest}")
            response, changes = _dispatch(request, action, target, data, if_match, service_key)
            record(
                request,
                action,
                target_type=action.split(".")[0],
                target_id=str(target),
                reason=data["reason"],
                changes=changes,
            )
            # An invitation secret is shown exactly once, never persisted in receipts/audit.
            stored = {k: v for k, v in response.items() if k != "invitationToken"}
            AdminCommandReceipt.objects.create(
                actor_id=actor.id,
                action=action,
                target_id=str(target),
                key_digest=key_digest,
                request_hash=request_hash,
                response_json=_json(stored),
            )
            return _json(response)
    except Exception as exc:
        # This runs after the mutation/savepoint rolled back. No payloads or exception text.
        record(
            request,
            action,
            target_type=action.split(".")[0],
            target_id=str(target),
            outcome="denied" if getattr(exc, "status_code", 500) in (401, 403) else "failed",
            reason=data.get("reason"),
            changes={},
        )
        raise


def _account_user(target):
    return _get(TaskillerUser.objects.select_for_update(), id=target)


def _account_eligibility(user, action):
    if action in {"suspend", "reactivate"}:
        if AccountDeletionRequest.objects.filter(user_id=user.id).exists():
            raise _error(409, "account_deletion_pending", "Account deletion prevents this action")
        if action == "suspend" and (not user.is_active or user.suspended_at is not None):
            raise _error(409, "account_state_conflict", "Only active accounts can be suspended")
        if action == "reactivate" and (user.is_active or user.suspended_at is None):
            raise _error(
                409, "account_state_conflict", "Only suspended accounts can be reactivated"
            )
    if action == "recovery-email" and (not user.is_active or user.suspended_at is not None):
        raise _error(409, "account_state_conflict", "Account cannot receive recovery email")


def _account(action, target, data, if_match):
    if "sessionId" in data and action != "revoke-sessions":
        raise _error(422, "validation_error", "sessionId applies only to session revocation")
    user = _account_user(target)
    _account_eligibility(user, action)
    if action in {"suspend", "reactivate"}:
        require_etag(if_match, make_etag("user", user.id, user.version))
        now = timezone.now()
        user.is_active = action == "reactivate"
        user.suspended_at = now if action == "suspend" else None
        user.suspension_reason = data["reason"]["reasonCode"] if action == "suspend" else ""
        user.version += 1
        user.updated_at = now
        user.save(
            update_fields=[
                "is_active",
                "suspended_at",
                "suspension_reason",
                "version",
                "updated_at",
            ]
        )
        if action == "suspend":
            DjangoAuthService().revoke_all_sessions(user.id, "admin_suspension")
        return {
            "status": "completed",
            "targetId": str(user.id),
            "etag": make_etag("user", user.id, user.version),
        }, {"isActive": user.is_active, "suspended": user.suspended_at is not None}
    service = DjangoAuthService()
    if action == "recovery-email":
        service.request_password_reset(user.email)
        return {"status": "queued", "targetId": str(user.id)}, {}
    if "sessionId" in data:
        if not service.revoke_session(user.id, data["sessionId"], "admin_revocation"):
            raise _error(404, "not_found", "Session not found")
    else:
        service.revoke_all_sessions(user.id, "admin_revocation")
    return {"status": "completed", "targetId": str(user.id)}, {"operation": "revoke-sessions"}


def _job_policy(request, job):
    require_capability(request, "retry_jobs", target=job.id)
    if job.job_type == "data_export":
        require_capability(request, "manage_privacy", step_up=True, target=job.id)


def _retry(request, target):
    job = _get(OutboxJob.objects.select_for_update(), id=target)
    _job_policy(request, job)
    export = _retry_export(job, lock=True)
    now = timezone.now()
    export.status, export.failure_code = "queued", None
    export.save(update_fields=["status", "failure_code"])
    job.status, job.attempts, job.available_at, job.updated_at = "queued", 0, now, now
    job.locked_at = job.locked_by = job.lease_expires_at = None
    job.completed_at = job.last_error = None
    job.save(
        update_fields=[
            "status",
            "attempts",
            "available_at",
            "updated_at",
            "locked_at",
            "locked_by",
            "lease_expires_at",
            "completed_at",
            "last_error",
        ]
    )
    return {"status": "queued", "targetId": str(job.id)}, {"status": "queued"}


def _retry_export(job, *, lock=False):
    if job.status != "dead" or job.job_type not in RETRYABLE_JOB_TYPES:
        raise _error(409, "job_not_retryable", "Job is not eligible for retry")
    try:
        export_id = UUID(str(job.payload_json["exportRequestId"]))
        user_id = UUID(str(job.payload_json["userId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(409, "job_not_retryable", "Job references are invalid") from exc
    query = DataExportRequest.objects.select_for_update() if lock else DataExportRequest.objects
    export = _get(query, id=export_id, user_id=user_id)
    if export.status != "failed" or export.archive_bytes is not None:
        raise _error(409, "job_not_retryable", "Export is not eligible for retry")
    if not TaskillerUser.objects.filter(id=user_id, is_active=True).exists():
        raise _error(409, "job_not_retryable", "Export account is unavailable")
    if AccountDeletionRequest.objects.filter(user_id=user_id).exists():
        raise _error(409, "job_not_retryable", "Account deletion prevents export retry")
    return export


def _set_roles(user, roles):
    groups = list(Group.objects.filter(name__in=[GROUP_PREFIX + role for role in roles]))
    if len(groups) != len(roles):
        raise _error(409, "roles_unavailable", "Console role definitions are unavailable")
    user.groups.remove(*user.groups.filter(name__startswith=GROUP_PREFIX))
    user.groups.add(*groups)


def _protect_owner(enrollment):
    ensure_not_last_owner(enrollment)
    # Pending invitations must never satisfy the enrolled-Owner invariant.
    # Keep this explicit until every operator/helper path uses the same filter.
    enrolled_owners = (
        StaffEnrollment.objects.filter(
            enabled=True,
            user__is_active=True,
            user__is_staff=True,
            user__groups__name=GROUP_PREFIX + "Owner",
        )
        .exclude(mfa_secret_encrypted="")
        .distinct()
    )
    if enrolled_owners.filter(id=enrollment.id).exists() and enrolled_owners.count() <= 1:
        raise _error(409, "admin_last_owner", "The last enrolled Owner cannot lose access")


def _staff(request, action, target, data, if_match):
    if action == "invite":
        user_model = get_user_model()
        user = user_model.objects.select_for_update().filter(username=data["username"]).first()
        if user is not None:
            if user.pk == request.user.pk:
                raise _error(403, "self_grant_forbidden", "Self invitations are forbidden")
            if user.email.casefold() != data["email"].casefold() or not user.is_active:
                raise _error(409, "staff_identity_conflict", "Staff identity is not eligible")
            if (
                StaffEnrollment.objects.filter(user_id=user.pk, enabled=True)
                .exclude(mfa_secret_encrypted="")
                .exists()
            ):
                raise _error(409, "staff_already_enrolled", "Staff identity is already enrolled")
        else:
            user = user_model(username=data["username"], email=data["email"], is_staff=True)
            user.set_unusable_password()
            user.save()
        enrollment, _ = StaffEnrollment.objects.get_or_create(user=user, defaults={"enabled": True})
        if enrollment.mfa_secret_encrypted:
            raise _error(
                409, "staff_identity_conflict", "Previously enrolled staff require recovery"
            )
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        _set_roles(user, data["roles"])
        now = timezone.now()
        enrollment.enabled = True
        enrollment.version += 1
        enrollment.updated_at = now
        enrollment.save(update_fields=["enabled", "version", "updated_at"])
        StaffSession.objects.filter(enrollment=enrollment, revoked_at__isnull=True).update(
            revoked_at=now
        )
        StaffChallenge.objects.filter(enrollment=enrollment, consumed_at__isnull=True).update(
            consumed_at=now
        )
        token = secrets.token_urlsafe(32)
        challenge = StaffChallenge.objects.create(
            enrollment=enrollment,
            secret_digest=_digest(token),
            purpose="enrollment",
            expires_at=now + timedelta(hours=1),
            payload_json={"userId": str(user.pk), "roles": data["roles"]},
        )
        return {
            "status": "invited",
            "targetId": str(enrollment.id),
            "invitationId": str(challenge.id),
            "invitationToken": token,
            "expiresAt": challenge.expires_at,
        }, {"roles": data["roles"]}
    enrollment = _get(StaffEnrollment.objects.select_for_update(), id=target)
    user = get_user_model().objects.select_for_update().get(pk=enrollment.user_id)
    require_etag(if_match, make_etag("staff", enrollment.id, enrollment.version))
    current_roles = set(
        user.groups.filter(name__startswith=GROUP_PREFIX).values_list("name", flat=True)
    )
    if action == "roles":
        requested = {GROUP_PREFIX + role for role in data["roles"]}
        if user.pk == request.user.pk and requested - current_roles:
            raise _error(403, "self_grant_forbidden", "Self grants are forbidden")
        if GROUP_PREFIX + "Owner" in current_roles and GROUP_PREFIX + "Owner" not in requested:
            _protect_owner(enrollment)
        _set_roles(user, data["roles"])
        changes = {"roles": data["roles"]}
    else:
        _protect_owner(enrollment)
        enrollment.enabled = False
        changes = {"enabled": False}
    enrollment.version += 1
    enrollment.updated_at = timezone.now()
    enrollment.save(update_fields=["enabled", "version", "updated_at"])
    StaffSession.objects.filter(enrollment=enrollment, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    StaffChallenge.objects.filter(enrollment=enrollment, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    return {
        "status": "completed",
        "targetId": str(enrollment.id),
        "etag": make_etag("staff", enrollment.id, enrollment.version),
    }, changes


def _privacy(action, target, if_match, key):
    user = _account_user(target)
    if action == "export":
        row = request_data_export(user_id=user.id, idempotency_key="admin:" + key)
    else:
        row = schedule_account_deletion(user, if_match)
    return {"status": row.status, "requestId": str(row.id), "targetId": str(user.id)}, {}


def _work(target, data, if_match, key):
    from taskiller.django_api.execution_service import DjangoExecutionService
    from taskiller.django_api.focus_service import DjangoFocusService
    from taskiller.execution.schemas import CreateSessionEventRequest
    from taskiller.focus.schemas import UpdateFocusPlanRequest
    from taskiller.work.schemas import UpdateWorkItemRequest, UpdateWorkTypeRequest

    operation = data["operation"]
    mapping = {
        "update-item": (WorkItem, UpdateWorkItemRequest, DjangoWorkService, "update_work_item"),
        "update-type": (WorkType, UpdateWorkTypeRequest, DjangoWorkService, "update_work_type"),
        "update-plan": (FocusPlan, UpdateFocusPlanRequest, DjangoFocusService, "update_focus_plan"),
        "session-event": (
            ExecutionSession,
            CreateSessionEventRequest,
            DjangoExecutionService,
            "append_event",
        ),
    }
    model, schema, service_type, method = mapping[operation]
    # Domain services acquire the account namespace before locking the work row.
    row = _get(model.objects, id=target)
    if row.owner_id is None:
        raise _error(403, "system_work_type_immutable", "System work types cannot be corrected")
    _account_user(row.owner_id)
    payload = validate_payload(schema, data["correction"])
    if operation == "session-event" and payload.client_occurred_at is not None:
        raise _error(422, "historical_event_forbidden", "Staff events use server timestamps")
    service = service_type(row.owner_id)
    if operation == "session-event":
        getattr(service, method)(row.id, payload, "admin:" + key, if_match)
    else:
        getattr(service, method)(row.id, payload, if_match)
    # Do not persist private domain response bodies in receipts or audit.
    row.refresh_from_db(fields=["version"])
    kind = {
        "update-item": "work-item",
        "update-type": "work-type",
        "update-plan": "focus-plan",
        "session-event": "execution-session",
    }[operation]
    return {
        "status": "completed",
        "targetId": str(row.id),
        "etag": make_etag(kind, row.id, row.version),
    }, {"operation": operation}


def _dispatch(request, action, target, data, if_match, key):
    family, operation = action.split(".", 1)
    if family == "users" and operation in ACCOUNT_ACTIONS:
        return _account(operation, target, data, if_match)
    if action == "jobs.retry":
        return _retry(request, target)
    if family == "staff" and operation in STAFF_ACTIONS:
        return _staff(request, operation, target, data, if_match)
    if family == "privacy" and operation in {"export", "deletion"}:
        return _privacy(operation, target, if_match, key)
    if action == "work.correct":
        return _work(target, data, if_match, key)
    raise _error(422, "unknown_admin_action", "Unsupported administrative action")


def bulk_preview(request, data):
    _validate_bulk(data)
    results = []
    for target in data["targets"]:
        target_id = target["id"]
        try:
            action = _bulk_action(data["action"])
            payload = _bulk_payload(data, target)
            _policy(request, action, target_id)
            _preview_target(request, action, target_id, payload, target.get("etag"))
            results.append({"targetId": str(target_id), "eligible": True})
        except TaskillerAPIError as exc:
            results.append({"targetId": str(target_id), "eligible": False, "code": exc.code})
        except Exception:
            results.append(
                {"targetId": str(target_id), "eligible": False, "code": "internal_error"}
            )
    return {
        "count": len(results),
        "eligibleCount": sum(row["eligible"] for row in results),
        "results": results,
    }


def bulk_execute(request, data, *, key):
    _validate_bulk(data)
    key = require_idempotency_key(key)
    results = []
    for target in data["targets"]:
        target_id = target["id"]
        try:
            payload = _bulk_payload(data, target)
            result = execute(
                request,
                _bulk_action(data["action"]),
                target_id,
                payload,
                key=_digest(key + ":" + str(target_id)),
                if_match=target.get("etag"),
            )
            results.append({"targetId": str(target_id), "outcome": "success", "result": result})
        except TaskillerAPIError as exc:
            results.append(
                {
                    "targetId": str(target_id),
                    "outcome": "failed",
                    "code": exc.code,
                    "status": exc.status_code,
                }
            )
        except Exception:
            results.append(
                {
                    "targetId": str(target_id),
                    "outcome": "failed",
                    "code": "internal_error",
                    "status": 500,
                }
            )
    return {"count": len(results), "results": results}


def _validate_bulk(data):
    targets = data.get("targets", [])
    if (
        data.get("action") not in BULK_ACTIONS
        or not 1 <= len(targets) <= 50
        or len({str(target["id"]) for target in targets}) != len(targets)
    ):
        raise _error(422, "validation_error", "Bulk targets must be unique and bounded to 50")


def _bulk_action(action):
    return "users." + action if action in ACCOUNT_ACTIONS else action


def _bulk_payload(data, target):
    from rest_framework.exceptions import ValidationError

    action = _bulk_action(data["action"])
    serializer_type = CommandSerializer
    if action.startswith("users."):
        serializer_type = AccountCommandSerializer
    elif action == "staff.roles":
        serializer_type = RolesSerializer
    elif action == "work.correct":
        serializer_type = WorkCorrectionSerializer
    payload = {
        "reason": data["reason"],
        **{key: value for key, value in target.items() if key not in {"id", "etag"}},
    }
    serializer = serializer_type(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as exc:
        raise _error(422, "validation_error", "Invalid command target payload") from exc
    return serializer.validated_data


def _preview_target(request, action, target, payload, if_match):
    if action.startswith("users.") or action.startswith("privacy."):
        user = _get(TaskillerUser.objects, id=target)
        operation = action.split(".", 1)[1]
        if action.startswith("users."):
            _account_eligibility(user, operation)
        if operation in {"suspend", "reactivate", "deletion"}:
            require_etag(if_match, make_etag("user", user.id, user.version))
        if "sessionId" in payload:
            if operation != "revoke-sessions":
                raise _error(422, "validation_error", "Unexpected sessionId")
            _get(AuthSession.objects, id=payload["sessionId"], user_id=user.id)
        return
    if action.startswith("staff."):
        enrollment = _get(StaffEnrollment.objects.select_related("user"), id=target)
        require_etag(if_match, make_etag("staff", enrollment.id, enrollment.version))
        current = set(
            enrollment.user.groups.filter(name__startswith=GROUP_PREFIX).values_list(
                "name", flat=True
            )
        )
        requested = {GROUP_PREFIX + role for role in payload.get("roles", [])}
        if (
            action == "staff.roles"
            and enrollment.user_id == request.user.pk
            and requested - current
        ):
            raise _error(403, "self_grant_forbidden", "Self grants are forbidden")
        if action == "staff.revoke-access" or GROUP_PREFIX + "Owner" not in requested:
            _protect_owner(enrollment)
        return
    if action == "jobs.retry":
        job = _get(OutboxJob.objects, id=target)
        _job_policy(request, job)
        _retry_export(job)
        return
    if action == "work.correct":
        from taskiller.execution.schemas import CreateSessionEventRequest
        from taskiller.focus.schemas import UpdateFocusPlanRequest
        from taskiller.work.schemas import UpdateWorkItemRequest, UpdateWorkTypeRequest

        model, schema, kind = {
            "update-item": (WorkItem, UpdateWorkItemRequest, "work-item"),
            "update-type": (WorkType, UpdateWorkTypeRequest, "work-type"),
            "update-plan": (FocusPlan, UpdateFocusPlanRequest, "focus-plan"),
            "session-event": (ExecutionSession, CreateSessionEventRequest, "execution-session"),
        }[payload["operation"]]
        row = _get(model.objects, id=target)
        if row.owner_id is None:
            raise _error(403, "system_work_type_immutable", "System work types cannot be corrected")
        require_etag(if_match, make_etag(kind, row.id, row.version))
        correction = validate_payload(schema, payload["correction"])
        if payload["operation"] == "session-event" and correction.client_occurred_at is not None:
            raise _error(422, "historical_event_forbidden", "Staff events use server timestamps")
