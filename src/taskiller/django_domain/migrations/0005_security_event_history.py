# ruff: noqa: RUF012
"""Keep security history append-only except for the retention worker."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0004_relationship_guards")]
    operations = [
        migrations.RunSQL(
            """
        CREATE OR REPLACE FUNCTION taskiller_guard_security_history() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('taskiller.retention', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Security events are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER tk_security_event_history BEFORE UPDATE OR DELETE ON security_events
            FOR EACH ROW EXECUTE FUNCTION taskiller_guard_security_history();
        """,
            reverse_sql="""
        DROP TRIGGER IF EXISTS tk_security_event_history ON security_events;
        DROP FUNCTION IF EXISTS taskiller_guard_security_history();
        """,
        )
    ]
