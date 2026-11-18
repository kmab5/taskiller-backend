from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create/update the Django Admin superuser from environment variables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--if-configured",
            action="store_true",
            help="Skip bootstrap when TASKILLER_ADMIN_PASSWORD is absent (for startup).",
        )

    def handle(self, *args, **options) -> None:
        del args
        email = os.getenv("TASKILLER_ADMIN_EMAIL", "").strip().casefold()
        password = os.getenv("TASKILLER_ADMIN_PASSWORD", "")

        if options.get("if_configured") and not password:
            self.stdout.write("Django Admin bootstrap skipped: no admin password configured.")
            return

        if not email:
            raise CommandError("TASKILLER_ADMIN_EMAIL is required")
        if len(password) < 12:
            raise CommandError("TASKILLER_ADMIN_PASSWORD must contain at least 12 characters")

        User = get_user_model()
        username = os.getenv("TASKILLER_ADMIN_USERNAME", "").strip() or email
        lookup = {User.USERNAME_FIELD: username}
        user, created = User.objects.get_or_create(
            **lookup,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        # Avoid rehashing an unchanged password on every service restart.
        if not user.check_password(password):
            user.set_password(password)
        user.save()

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Django Admin superuser {action}: {username}"))
