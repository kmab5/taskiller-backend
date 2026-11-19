# ruff: noqa: RUF012
"""Reconcile UUID primary-key serialization metadata after deployed migration 0006.

Django Options.setup_pk() marks model primary keys serialize=False. The manually
created fields in 0006 omitted that flag, leaving migration state inconsistent
with the bound models. This is only serialization metadata: preserve the deployed
UUID columns, defaults, existing values, constraints and append-only triggers.
"""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0008_console_query_indexes")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="adminauditrecord",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                migrations.AlterField(
                    model_name="admincommandreceipt",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                migrations.AlterField(
                    model_name="staffchallenge",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                migrations.AlterField(
                    model_name="staffenrollment",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                migrations.AlterField(
                    model_name="staffrecoverycode",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                migrations.AlterField(
                    model_name="staffsession",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
            ],
        ),
    ]
