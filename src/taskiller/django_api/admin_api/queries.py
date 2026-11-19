"""Allowlisted console projections; authorization precedes all querying in read_views."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from django.core import signing
from django.db.models import CharField, Exists, OuterRef, Prefetch, Q
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from taskiller.django_domain import models as m

CURSOR_SALT = "taskiller.admin.reads.v1"
CURSOR_MAX_AGE = 3600
# Neither arbitrary actions nor arbitrary security event names are directory metadata.
SECURITY_EVENTS = (
    "login_success",
    "login_failed",
    "password_reset_requested",
    "password_reset_completed",
    "email_verified",
    "refresh_token_reuse",
    "logout",
    "sessions_revoked",
)
ADMIN_AUDIT_ACTIONS = (
    "user.suspend",
    "user.reactivate",
    "user.recovery_email",
    "user.revoke_sessions",
    "users.suspend",
    "users.reactivate",
    "users.recovery-email",
    "users.revoke-sessions",
    "account.suspend",
    "account.reactivate",
    "account.recovery_email",
    "account.revoke_sessions",
    "job.retry",
    "jobs.retry",
)


def decode_cursor(value):
    try:
        data = signing.loads(value, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE)
        if not isinstance(data, dict) or set(data) != {
            "scope",
            "filters",
            "start",
            "end",
            "at",
            "id",
        }:
            raise ValueError
        UUID(data["id"])
        for key in ("at", "start", "end"):
            if datetime.fromisoformat(data[key]).utcoffset() is None:
                raise ValueError
        return data
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise ValidationError({"cursor": "Invalid or expired cursor."}) from exc


def fingerprint(filters):
    values = {k: str(v) for k, v in filters.items() if k not in {"cursor", "limit"}}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def bounded(qs, filters, field="created_at"):
    return qs.filter(**{f"{field}__gte": filters["start"], f"{field}__lt": filters["end"]})


def page(qs, filters, scope, project, field="created_at"):
    digest = fingerprint(filters)
    if filters.get("cursor"):
        cursor = decode_cursor(filters["cursor"])
        if cursor["scope"] != scope or cursor["filters"] != digest:
            raise ValidationError({"cursor": "Cursor does not match this request."})
        at = datetime.fromisoformat(cursor["at"])
        qs = qs.filter(Q(**{f"{field}__lt": at}) | Q(**{field: at, "id__lt": cursor["id"]}))
    rows = list(qs.order_by(f"-{field}", "-id")[: filters["limit"] + 1])
    more = len(rows) > filters["limit"]
    rows = rows[: filters["limit"]]
    token = None
    if more:
        last = rows[-1]
        token = signing.dumps(
            {
                "scope": scope,
                "filters": digest,
                "start": filters["start"].isoformat(),
                "end": filters["end"].isoformat(),
                "at": getattr(last, field).astimezone(UTC).isoformat(),
                "id": str(last.id),
            },
            salt=CURSOR_SALT,
            compress=True,
        )
    return {"items": [project(row) for row in rows], "nextCursor": token}


def users_queryset():
    pending = m.AccountDeletionRequest.objects.filter(
        user_id=OuterRef("pk"), status__in=["pending", "scheduled", "queued", "running"]
    )
    return m.TaskillerUser.objects.annotate(pending_deletion=Exists(pending)).defer("password_hash")


def lifecycle(row):
    if row.pending_deletion:
        return "pending_deletion"
    if getattr(row, "suspended_at", None) is not None:
        return "suspended"
    return "active" if row.is_active else "inactive"


def user_projection(row):
    return {
        "id": row.id,
        "email": row.email,
        "displayName": row.display_name,
        "lifecycle": lifecycle(row),
        "emailVerified": row.email_verified_at is not None,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "version": row.version,
    }


def users(filters, scope):
    qs = bounded(users_queryset(), filters)
    if query := filters.get("query"):
        # Exact email and anchored display-name matching avoid unbounded substring scans.
        qs = qs.filter(Q(email__iexact=query) | Q(display_name__istartswith=query))
    if "verified" in filters:
        qs = qs.filter(email_verified_at__isnull=not filters["verified"])
    state = filters.get("lifecycle")
    if state == "pending_deletion":
        qs = qs.filter(pending_deletion=True)
    elif state:
        qs = qs.filter(pending_deletion=False)
        if state == "suspended":
            qs = qs.filter(suspended_at__isnull=False)
        else:
            qs = qs.filter(suspended_at__isnull=True, is_active=state == "active")
    return page(qs, filters, scope, user_projection)


def session_projection(row):
    return {
        "id": row.id,
        "deviceName": row.device_name,
        "createdAt": row.created_at,
        "lastUsedAt": row.last_used_at,
        "expiresAt": row.expires_at,
        "revokedAt": row.revoked_at,
    }


def activity(filters, scope, user_id, security=False):
    events = bounded(m.SessionEvent.objects.filter(owner_id=user_id), filters, "occurred_at")
    # Normalize both streams in SQL; no payload or security metadata is selected.
    from django.db.models import CharField, F, Value

    events = events.annotate(
        timestamp=F("occurred_at"), source=Value("execution_event", output_field=CharField())
    ).values("id", "timestamp", "type", "source")
    if security:
        security_rows = (
            bounded(
                m.SecurityEvent.objects.filter(user_id=user_id, event_type__in=SECURITY_EVENTS),
                filters,
            )
            .annotate(
                timestamp=F("created_at"),
                type=F("event_type"),
                source=Value("security_event", output_field=CharField()),
            )
            .values("id", "timestamp", "type", "source")
        )
        events = events.union(security_rows, all=True)
    # UNION cannot be filtered after combination. Apply keyset to each branch first.
    if filters.get("cursor"):
        cursor = decode_cursor(filters["cursor"])
        if cursor["scope"] != scope or cursor["filters"] != fingerprint(filters):
            raise ValidationError({"cursor": "Cursor does not match this request."})
        at = datetime.fromisoformat(cursor["at"])
        condition = Q(timestamp__lt=at) | Q(timestamp=at, id__lt=cursor["id"])
        base = bounded(m.SessionEvent.objects.filter(owner_id=user_id), filters, "occurred_at")
        events = (
            base.annotate(
                timestamp=F("occurred_at"),
                source=Value("execution_event", output_field=CharField()),
            )
            .filter(condition)
            .values("id", "timestamp", "type", "source")
        )
        if security:
            events = events.union(security_rows.filter(condition), all=True)
    rows = list(events.order_by("-timestamp", "-id")[: filters["limit"] + 1])
    token = None
    if len(rows) > filters["limit"]:
        last = rows[filters["limit"] - 1]
        token = signing.dumps(
            {
                "scope": scope,
                "filters": fingerprint(filters),
                "start": filters["start"].isoformat(),
                "end": filters["end"].isoformat(),
                "at": last["timestamp"].astimezone(UTC).isoformat(),
                "id": str(last["id"]),
            },
            salt=CURSOR_SALT,
            compress=True,
        )
    return {"items": rows[: filters["limit"]], "nextCursor": token}


def job_projection(row):
    return {
        "id": row.id,
        "type": row.job_type,
        "state": row.status,
        "attempts": row.attempts,
        "maxAttempts": row.max_attempts,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "availableAt": row.available_at,
        # Retry eligibility is intentionally conservative; commands recheck under lock.
        "eligibleActions": ["retry"]
        if (
            row.status == "dead"
            and row.job_type == "data_export"
            and getattr(row, "eligible_retry", False)
        )
        else [],
    }


def job_types(include_privacy=False):
    types = ["auth_email", "retention"]
    return types + ["data_export", "account_delete"] if include_privacy else types


def jobs(filters, scope, *, include_privacy=False, retry=False):
    qs = bounded(m.OutboxJob.objects.all(), filters).only(
        "id",
        "job_type",
        "status",
        "attempts",
        "max_attempts",
        "created_at",
        "updated_at",
        "available_at",
    )
    # Privacy queue existence is itself privileged.
    qs = qs.filter(job_type__in=job_types(include_privacy))
    if include_privacy and retry:
        exports = (
            m.DataExportRequest.objects.annotate(
                id_text=Cast("id", CharField()),
                user_text=Cast("user_id", CharField()),
            )
            .filter(
                id_text=OuterRef("export_ref"),
                user_text=OuterRef("user_ref"),
                status="failed",
                archive_bytes__isnull=True,
                user__is_active=True,
            )
            .exclude(user_id__in=m.AccountDeletionRequest.objects.values("user_id"))
        )
        qs = qs.annotate(
            export_ref=KT("payload_json__exportRequestId"),
            user_ref=KT("payload_json__userId"),
        ).annotate(eligible_retry=Exists(exports))
        # The state and type guards are part of the final projection as well.

    for key, field in (("type", "job_type"), ("state", "status")):
        if key in filters:
            qs = qs.filter(**{field: filters[key]})
    return page(qs, filters, scope, job_projection)


def privacy_queryset(kind, filters):
    model = m.DataExportRequest if kind == "export" else m.AccountDeletionRequest
    field = "created_at" if kind == "export" else "requested_at"
    qs = bounded(model.objects.all(), filters, field)
    if "state" in filters:
        qs = qs.filter(status=filters["state"])
    if "userId" in filters:
        qs = qs.filter(user_id=filters["userId"])
    return qs.only("id", "user_id", "status", field, "completed_at"), field


def privacy_projection(row, kind):
    return {
        "id": row.id,
        "userId": row.user_id,
        "type": kind,
        "state": row.status,
        "createdAt": row.created_at if kind == "export" else row.requested_at,
        "completedAt": row.completed_at,
    }


def scoped_audit(owner):
    qs = m.AdminAuditRecord.objects.only(
        "id",
        "actor_id",
        "action",
        "target_type",
        "target_id",
        "created_at",
        "request_id",
        "outcome",
        "reason_code",
        "changes_json",
    )
    if not owner:
        # Exclude historical Owner/staff actors as well as current privileged identities.
        # Their IDs remain excluded after offboarding when a staff audit row exists.
        privileged = m.StaffEnrollment.objects.filter(
            user__groups__name="taskiller-console:Owner"
        ).values_list("pk", flat=True)
        staff_actors = m.AdminAuditRecord.objects.filter(
            Q(target_type__in=["staff", "staff_enrollment", "role", "roles", "enrollment"])
            | Q(action__startswith="staff.")
            | Q(action__startswith="owner.")
        ).values_list("actor_id", flat=True)
        historical_owners = m.AdminAuditRecord.objects.filter(
            target_type__in=["staff", "staff_enrollment"],
            changes_json__roles__contains=["Owner"],
        ).values_list("target_id", flat=True)
        qs = (
            qs.filter(
                action__in=ADMIN_AUDIT_ACTIONS,
                target_type__in=["user", "users", "account", "job", "jobs", "outbox_job"],
            )
            .exclude(actor_id__in=[str(pk) for pk in privileged])
            .exclude(actor_id__in=historical_owners)
            .exclude(actor_id__in=staff_actors.filter(actor_id__isnull=False))
        )
    return qs


def audit_changes(raw, *, owner=False):
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key in ("version", "sessionCount", "attempts", "count"):
        value = raw.get(key)
        if type(value) is int and 0 <= value <= 2**63 - 1:
            result[key] = value
    for key in ("enabled", "isActive", "suspended"):
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    states = {
        "active",
        "inactive",
        "suspended",
        "queued",
        "running",
        "completed",
        "dead",
        "failed",
        "scheduled",
        "cancelled",
        "pending",
        "reactivated",
        "revoked",
    }
    for key in ("state", "status"):
        if isinstance(raw.get(key), str) and raw[key] in states:
            result[key] = raw[key]
    if isinstance(raw.get("jobType"), str) and raw["jobType"] in {"auth_email", "retention"}:
        result["jobType"] = raw["jobType"]
    if owner:
        if isinstance(raw.get("jobType"), str) and raw["jobType"] in {
            "data_export",
            "account_delete",
        }:
            result["jobType"] = raw["jobType"]
        if isinstance(raw.get("roles"), list):
            result["roles"] = [
                role
                for role in raw["roles"]
                if isinstance(role, str)
                and role in {"Owner", "Administrator", "Support", "Analyst"}
            ]
        if isinstance(raw.get("capabilities"), list):
            from .permissions import CAPABILITIES

            result["capabilities"] = [
                cap for cap in raw["capabilities"] if isinstance(cap, str) and cap in CAPABILITIES
            ]
    return result


def audit_projection(row, *, owner=False):
    return {
        "id": row.id,
        "actorId": row.actor_id,
        "action": row.action,
        "targetType": row.target_type,
        "targetId": row.target_id,
        "timestamp": row.created_at,
        "requestId": row.request_id,
        "outcome": row.outcome,
        "reasonCode": row.reason_code,
        "changes": audit_changes(row.changes_json, owner=owner),
    }


WORK_MODELS = {
    "project": m.WorkItem,
    "sprint": m.WorkItem,
    "chore": m.WorkItem,
    "work_type": m.WorkType,
    "focus_plan": m.FocusPlan,
    "execution_session": m.ExecutionSession,
}


WORK_ETAG_KINDS = {
    "project": "work-item",
    "sprint": "work-item",
    "chore": "work-item",
    "work_type": "work-type",
    "focus_plan": "focus-plan",
    "execution_session": "execution-session",
}


# Explicit detail allowlists never traverse reviews or deserialize stored snapshots.
WORK_ITEM_DETAIL_FIELDS = {
    "description": "description",
    "priority": "priority",
    "workTypeId": "work_type_id",
    "dueAt": "deadline_at",
    "plannedStartAt": "planned_start_at",
    "estimatedEffortSeconds": "estimated_effort_seconds",
    "targetStartDate": "target_start_date",
    "targetEndDate": "target_end_date",
    "completedAt": "completed_at",
    "cancelledAt": "cancelled_at",
    "archivedAt": "archived_at",
    "deletedAt": "deleted_at",
}
WORK_DETAIL_FIELDS = {
    "project": WORK_ITEM_DETAIL_FIELDS,
    "sprint": WORK_ITEM_DETAIL_FIELDS,
    "chore": WORK_ITEM_DETAIL_FIELDS,
    "work_type": {
        "description": "description",
        "slug": "slug",
        "isSystem": "is_system",
        "cognitiveDemand": "cognitive_demand",
        "interruptionSensitivity": "interruption_sensitivity",
        "continuityNeed": "continuity_need",
        "repetitiveness": "repetitiveness",
        "physicality": "physicality",
        "learningMode": "learning_mode",
    },
    "focus_plan": {"source": "source", "isTemplate": "is_template", "deletedAt": "deleted_at"},
    "execution_session": {
        "currentSegmentIndex": "current_segment_index",
        "sessionStartedAt": "session_started_at",
        "currentSegmentStartedAt": "current_segment_started_at",
        "pausedAt": "paused_at",
        "endedAt": "ended_at",
    },
}


def segment_projection(row):
    return {
        "id": row.id,
        "segmentIndex": row.segment_index,
        "kind": row.kind,
        "durationMode": row.duration_mode,
        "targetSeconds": row.target_seconds,
        "minSeconds": row.min_seconds,
        "maxSeconds": row.max_seconds,
        "linkedWorkItemId": row.linked_work_item_id,
        "optional": row.optional,
        "label": row.label,
    }


def work_queryset(kind, owner_id=None, *, detail=False):
    qs = WORK_MODELS[kind].objects.all()
    if owner_id is not None:
        qs = qs.filter(owner_id=owner_id)
    if kind in {"project", "sprint", "chore"}:
        qs = qs.filter(kind=kind)
        fields = ["name", "status", "parent_id"]
    elif kind == "execution_session":
        fields = ["state", "work_item_id", "focus_plan_id"]
    elif kind == "focus_plan":
        fields = ["name", "work_item_id"]
    else:
        fields = ["display_name"]
    if detail:
        fields += list(WORK_DETAIL_FIELDS[kind].values())
        if kind == "focus_plan":
            segments = m.FocusPlanSegment.objects.only(
                "id",
                "focus_plan_id",
                "segment_index",
                "kind",
                "duration_mode",
                "target_seconds",
                "min_seconds",
                "max_seconds",
                "linked_work_item_id",
                "optional",
                "label",
            ).order_by("segment_index", "id")
            qs = qs.prefetch_related(
                Prefetch("taskiller_segments", queryset=segments, to_attr="admin_segments")
            )
    return qs.only("id", "owner_id", "created_at", "updated_at", "version", *fields)


def work_projection(row, kind, *, detail=False):
    result = {
        "id": row.id,
        "ownerId": row.owner_id,
        "kind": kind,
        "name": getattr(row, "name", getattr(row, "display_name", None)),
        "state": getattr(row, "status", getattr(row, "state", None)),
        "parentId": getattr(row, "parent_id", None),
        "workItemId": getattr(row, "work_item_id", None),
        "focusPlanId": getattr(row, "focus_plan_id", None),
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "version": row.version,
    }
    if detail:
        result.update({key: getattr(row, field) for key, field in WORK_DETAIL_FIELDS[kind].items()})
        if kind == "focus_plan":
            result["segments"] = [segment_projection(segment) for segment in row.admin_segments]
    return result


def overview(filters, operations=False, *, include_privacy=False):
    completed = bounded(m.ExecutionSession.objects.filter(state="completed"), filters, "ended_at")
    signal = None
    queued = failed = None
    if operations:
        jobs = bounded(m.OutboxJob.objects.filter(job_type__in=job_types(include_privacy)), filters)
        queued = jobs.filter(status="queued").count()
        failed = jobs.filter(status="dead").count()
        signal = (
            bounded(
                m.OutboxJob.objects.filter(job_type__in=job_types(include_privacy)),
                filters,
                "completed_at",
            )
            .order_by("-completed_at")
            .values_list("completed_at", flat=True)
            .first()
        )
    return {
        "start": filters["start"],
        "end": filters["end"],
        "observedAt": timezone.now(),
        "registrations": bounded(m.TaskillerUser.objects.all(), filters).count(),
        "completedExecutionSessions": completed.count(),
        "accountsWithExecutionActivity": bounded(
            m.SessionEvent.objects.all(), filters, "occurred_at"
        )
        .values("owner_id")
        .distinct()
        .count(),
        "queuedJobs": queued,
        "failedJobs": failed,
        "latestWorkerSignalAt": signal,
        "workerSignalSource": "outbox_job.completed_at" if signal else None,
    }
