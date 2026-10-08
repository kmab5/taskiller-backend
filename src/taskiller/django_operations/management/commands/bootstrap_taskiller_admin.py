from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create/update the Django Admin superuser from environment variables."

    def handle(self, *args, **options) -> None:
        del args, options
        email = os.getenv("TASKILLER_ADMIN_EMAIL", "").strip().casefold()
        password = os.getenv("TASKILLER_ADMIN_PASSWORD", "")

        if not email:
            raise CommandError("TASKILLER_ADMIN_EMAIL is required")
        if len(password) < 12:
            raise CommandError("TASKILLER_ADMIN_PASSWORD must contain at least 12 characters")

        User = get_user_model()
        lookup = {User.USERNAME_FIELD: email}
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
        user.set_password(password)
        user.save()

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Django Admin superuser {action}: {email}"))
