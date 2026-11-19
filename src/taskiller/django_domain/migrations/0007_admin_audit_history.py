# ruff: noqa: RUF012
"""Audit history is immutable except bounded, operator-authorized retention.

A database operator must provision the NOLOGIN role taskiller_audit_retention
and grant membership only to a separate retention login, never the application.
Within a transaction that login sets taskiller.admin_audit_retention to 'on'
and taskiller.admin_audit_retention_before to an explicit timestamptz cutoff,
then deletes rows older than that cutoff. No runtime path grants membership.
UPDATE and TRUNCATE remain forbidden even to the retention login. Database
owners can alter DDL; deploy/runtime credentials must be managed accordingly.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0006_staff_console_models")]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE FUNCTION taskiller_guard_admin_audit() RETURNS trigger AS $$
            DECLARE
                cutoff timestamptz;
            BEGIN
                IF TG_OP = 'DELETE'
                   AND current_setting('taskiller.admin_audit_retention', true) = 'on'
                   AND EXISTS (
                       SELECT 1 FROM pg_roles
                       WHERE rolname = 'taskiller_audit_retention'
                         AND pg_has_role(current_user, oid, 'MEMBER')
                   ) THEN
                    cutoff := nullif(current_setting(
                        'taskiller.admin_audit_retention_before', true
                    ), '')::timestamptz;
                    IF cutoff IS NOT NULL AND cutoff <= statement_timestamp()
                       AND OLD.created_at < cutoff THEN
                        RETURN OLD;
                    END IF;
                END IF;
                RAISE EXCEPTION 'Administrative audit records are append-only'
                    USING ERRCODE = '23514';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER tk_admin_audit_history
                BEFORE UPDATE OR DELETE ON admin_audit_records
                FOR EACH ROW EXECUTE FUNCTION taskiller_guard_admin_audit();
            CREATE TRIGGER tk_admin_audit_no_truncate
                BEFORE TRUNCATE ON admin_audit_records
                FOR EACH STATEMENT EXECUTE FUNCTION taskiller_guard_admin_audit();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS tk_admin_audit_no_truncate ON admin_audit_records;
            DROP TRIGGER IF EXISTS tk_admin_audit_history ON admin_audit_records;
            DROP FUNCTION IF EXISTS taskiller_guard_admin_audit();
            """,
        ),
    ]
