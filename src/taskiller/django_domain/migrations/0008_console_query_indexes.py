# ruff: noqa: RUF012
"""Indexes for confirmed bounded console query patterns."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0007_admin_audit_history")]
    operations = [
        migrations.AddIndex(
            model_name="taskilleruser",
            index=models.Index(fields=["-created_at", "-id"], name="tk_admin_users_cursor"),
        ),
        migrations.AddIndex(
            model_name="authsession",
            index=models.Index(
                fields=["user", "-created_at", "-id"], name="tk_admin_devices_cursor"
            ),
        ),
        migrations.AddIndex(
            model_name="executionsession",
            index=models.Index(
                fields=["state", "ended_at", "id"], name="tk_admin_completed_sessions"
            ),
        ),
        migrations.AddIndex(
            model_name="sessionevent",
            index=models.Index(
                fields=["owner", "-occurred_at", "-id"], name="tk_admin_activity_cursor"
            ),
        ),
        migrations.AddIndex(
            model_name="sessionevent",
            index=models.Index(fields=["occurred_at", "owner"], name="tk_admin_activity_metrics"),
        ),
        migrations.AddIndex(
            model_name="outboxjob",
            index=models.Index(
                fields=["job_type", "-created_at", "-id"], name="tk_admin_jobs_cursor"
            ),
        ),
        migrations.AddIndex(
            model_name="staffenrollment",
            index=models.Index(fields=["-created_at", "-id"], name="tk_admin_staff_cursor"),
        ),
    ]
