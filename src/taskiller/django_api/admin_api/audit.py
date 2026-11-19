from __future__ import annotations

from taskiller.django_domain.models import AdminAuditRecord

SAFE_CHANGE_FIELDS = frozenset(
    {
        "state",
        "status",
        "version",
        "roles",
        "enabled",
        "sessionCount",
        "jobType",
        "attempts",
        "isActive",
        "suspended",
        "count",
        "operation",
        "requestId",
        "reasonCode",
        "capabilities",
    }
)


def record(
    request,
    action,
    target_type="",
    target_id="",
    outcome="success",
    reason=None,
    changes=None,
    actor_id=None,
):
    session = getattr(request, "_auth", None) if request is not None else None
    actor_id = (
        str(actor_id)
        if actor_id is not None
        else (str(session.enrollment_id) if session is not None else None)
    )
    reason_code, comment = "", ""
    if isinstance(reason, dict):
        reason_code = str(reason.get("reasonCode", ""))[:80]
        comment = str(reason.get("comment", ""))[:500]
    elif reason:
        reason_code = str(reason)[:80]
    return AdminAuditRecord.objects.create(
        actor_id=actor_id,
        action=action[:100],
        target_type=target_type[:80],
        target_id=str(target_id)[:128],
        outcome=outcome[:30],
        reason_code=reason_code,
        comment=comment,
        changes_json={k: v for k, v in (changes or {}).items() if k in SAFE_CHANGE_FIELDS},
        request_id=str(getattr(request, "taskiller_request_id", ""))[:100],
    )
