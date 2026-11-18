from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections, connections

from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_operations.worker_service import (
    claim_job,
    ensure_retention_job,
    fail_job,
    process_job,
    recover_expired_leases,
    worker_id,
)


class Command(BaseCommand):
    help = "Run the Django-native Taskiller PostgreSQL outbox worker."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one available job.",
        )

    def handle(self, *args, **options) -> None:
        del args
        settings = taskiller_settings()
        once = bool(options["once"])
        identity = worker_id()
        next_maintenance = 0.0
        while True:
            claim = None
            try:
                close_old_connections()
                if time.monotonic() >= next_maintenance:
                    recover_expired_leases()
                    ensure_retention_job()
                    next_maintenance = time.monotonic() + 15
                claim = claim_job(identity, with_token=True)
                if claim is not None:
                    job_id, token = claim
                    try:
                        process_job(job_id, claim_token=token)
                    except Exception as exc:
                        if isinstance(exc, DatabaseError):
                            connections.close_all()
                        fail_job(job_id, exc, claim_token=token)
                        self.stderr.write(f"outbox job {job_id} failed: {type(exc).__name__}")
                if once:
                    return
            except DatabaseError as exc:
                connections.close_all()
                next_maintenance = 0.0
                self.stderr.write(f"outbox database unavailable: {type(exc).__name__}")
            time.sleep(settings.outbox_poll_seconds)
