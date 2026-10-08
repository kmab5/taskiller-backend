"""Exercise Django Execution behavior on the Alembic-owned test schema."""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")

import django

django.setup()

from django.test import Client  # noqa: E402


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def main() -> None:
    client = Client()
    email = f"django-phase6-{uuid4().hex}@example.com"
    password = "Taskiller-phase6-password"

    register = client.post(
        "/api/v1/auth/register",
        data={
            "email": email,
            "password": password,
            "timezone": "Europe/Istanbul",
            "locale": "en",
        },
        content_type="application/json",
    )
    if register.status_code != 201:
        raise SystemExit("register failed")
    token = register.json()["accessToken"]
    auth = bearer(token)

    types = client.get("/api/v1/work-types", **auth).json()["items"]
    work_type = next((item for item in types if item["slug"] == "programming"), types[0])

    chore = client.post(
        "/api/v1/work-items",
        data={
            "kind": "chore",
            "workTypeId": work_type["id"],
            "name": "Phase 6 execution chore",
            "status": "ready",
            "estimatedEffortSeconds": 1800,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-work-{uuid4().hex}",
        **auth,
    )
    if chore.status_code != 201:
        raise SystemExit("work create failed")
    work_id = chore.json()["id"]

    plan = client.post(
        "/api/v1/focus-plans",
        data={
            "workItemId": work_id,
            "source": "manual",
            "name": "Phase 6 Plan",
            "template": False,
            "segments": [
                {
                    "kind": "work",
                    "durationMode": "fixed",
                    "targetSeconds": 1200,
                    "linkedWorkItemId": work_id,
                    "optional": False,
                    "label": "Work",
                },
                {
                    "kind": "break",
                    "durationMode": "fixed",
                    "targetSeconds": 300,
                    "optional": True,
                    "label": "Break",
                },
            ],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-plan-{uuid4().hex}",
        **auth,
    )
    if plan.status_code != 201:
        raise SystemExit(f"focus plan failed: {plan.content!r}")

    start = client.post(
        "/api/v1/execution-sessions",
        data={
            "workItemId": work_id,
            "focusPlanId": plan.json()["id"],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-start-{uuid4().hex}",
        **auth,
    )
    if start.status_code != 201:
        raise SystemExit(f"start failed: {start.status_code} {start.content!r}")
    session_id = start.json()["id"]
    etag = start.headers.get("ETag")

    active = client.get("/api/v1/execution-sessions/active", **auth)
    if active.status_code != 200 or active.json()["session"]["id"] != session_id:
        raise SystemExit("active session lookup failed")

    pause_key = f"phase6-pause-{uuid4().hex}"
    pause = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "paused", "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=pause_key,
        HTTP_IF_MATCH=etag,
        **auth,
    )
    if pause.status_code != 201 or pause.json()["session"]["state"] != "paused":
        raise SystemExit(f"pause failed: {pause.content!r}")

    replay = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "paused", "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=pause_key,
        HTTP_IF_MATCH='"stale"',
        **auth,
    )
    if replay.status_code != 201 or replay.json() != pause.json():
        raise SystemExit("event replay did not return original result")

    resume = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "resumed", "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-resume-{uuid4().hex}",
        HTTP_IF_MATCH=pause.headers.get("ETag"),
        **auth,
    )
    if resume.status_code != 201:
        raise SystemExit("resume failed")

    complete_segment = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "segment_completed", "segmentIndex": 0, "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-segment-{uuid4().hex}",
        HTTP_IF_MATCH=resume.headers.get("ETag"),
        **auth,
    )
    if complete_segment.status_code != 201:
        raise SystemExit(f"segment complete failed: {complete_segment.content!r}")

    break_started = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "break_started", "segmentIndex": 1, "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-break-start-{uuid4().hex}",
        HTTP_IF_MATCH=complete_segment.headers.get("ETag"),
        **auth,
    )
    if break_started.status_code != 201:
        raise SystemExit(f"break start failed: {break_started.content!r}")

    break_end = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "break_ended", "segmentIndex": 1, "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-break-end-{uuid4().hex}",
        HTTP_IF_MATCH=break_started.headers.get("ETag"),
        **auth,
    )
    if break_end.status_code != 201:
        raise SystemExit("break end failed")

    terminal = client.post(
        f"/api/v1/execution-sessions/{session_id}/events",
        data={"type": "session_completed", "payload": {}},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-finish-{uuid4().hex}",
        HTTP_IF_MATCH=break_end.headers.get("ETag"),
        **auth,
    )
    if terminal.status_code != 201 or terminal.json()["session"]["state"] != "completed":
        raise SystemExit("session completion failed")

    review = client.put(
        f"/api/v1/execution-sessions/{session_id}/review",
        data={
            "focusScore": 4,
            "fatigueScore": 2,
            "difficultyScore": 3,
            "satisfactionScore": 5,
            "note": "Phase 6",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"phase6-review-{uuid4().hex}",
        **auth,
    )
    if review.status_code != 200 or review.json()["focusScore"] != 4:
        raise SystemExit("review failed")

    events = client.get(
        f"/api/v1/execution-sessions/{session_id}/events",
        **auth,
    )
    if events.status_code != 200 or len(events.json()["items"]) < 7:
        raise SystemExit("event history failed")

    print(
        "django phase-6 Execution smoke OK: start, active lookup, pause/replay/resume, "
        "segment/break lifecycle, completion, review, event history"
    )


if __name__ == "__main__":
    main()
