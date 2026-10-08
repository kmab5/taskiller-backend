from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from taskiller.django_api.runtime import taskiller_settings
from taskiller.django_operations.worker_service import (
    claim_job,
    ensure_retention_job,
    fail_job,
    finish_job,
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
        recover_expired_leases()
        ensure_retention_job()
        identity = worker_id()

        while True:
            job_id = claim_job(identity)
            if job_id is None:
                if once:
                    return
                time.sleep(settings.outbox_poll_seconds)
                continue
            try:
                process_job(job_id)
                finish_job(job_id)
            except Exception as exc:
                fail_job(job_id, exc)
                self.stderr.write(self.style.ERROR(f"outbox job {job_id} failed: {exc}"))
            if once:
                return
