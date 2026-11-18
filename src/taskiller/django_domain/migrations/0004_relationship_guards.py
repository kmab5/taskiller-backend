# ruff: noqa: RUF012
"""Enforce current Django domain relationships independently of the API."""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION taskiller_validate_relationships() RETURNS trigger AS $$
DECLARE related record;
DECLARE target record;
BEGIN
    IF TG_TABLE_NAME = 'work_items' THEN
        IF NEW.parent_id IS NOT NULL THEN
            SELECT owner_id, kind INTO related FROM work_items WHERE id = NEW.parent_id;
            IF NOT FOUND OR related.owner_id <> NEW.owner_id
                OR (NEW.kind = 'sprint' AND related.kind <> 'project')
                OR (NEW.kind = 'chore' AND related.kind NOT IN ('project', 'sprint')) THEN
                RAISE EXCEPTION 'Invalid work item parent' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF EXISTS (SELECT 1 FROM work_items child WHERE child.parent_id = NEW.id AND
            (child.owner_id <> NEW.owner_id OR NEW.kind = 'chore'
             OR (child.kind = 'sprint' AND NEW.kind <> 'project'))) THEN
            RAISE EXCEPTION 'Invalid work item children' USING ERRCODE = '23514';
        END IF;
        IF NEW.work_type_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM work_types WHERE id = NEW.work_type_id
            AND (owner_id IS NULL OR owner_id = NEW.owner_id)) THEN
            RAISE EXCEPTION 'Invalid work type owner' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'focus_plan_recommendations' THEN
        IF NOT EXISTS (SELECT 1 FROM work_items WHERE id = NEW.work_item_id
                       AND owner_id = NEW.owner_id) THEN
            RAISE EXCEPTION 'Invalid recommendation owner' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'focus_plans' THEN
        IF NEW.work_item_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM work_items WHERE id = NEW.work_item_id AND owner_id = NEW.owner_id) THEN
            RAISE EXCEPTION 'Invalid plan work item owner' USING ERRCODE = '23514';
        END IF;
        IF NEW.recommendation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM focus_plan_recommendations WHERE id = NEW.recommendation_id
            AND owner_id = NEW.owner_id AND work_item_id = NEW.work_item_id) THEN
            RAISE EXCEPTION 'Invalid plan recommendation' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'focus_plan_segments' THEN
        IF NEW.linked_work_item_id IS NOT NULL THEN
            SELECT owner_id, work_item_id INTO target FROM focus_plans
                WHERE id = NEW.focus_plan_id;
            SELECT owner_id, kind, parent_id INTO related FROM work_items
                WHERE id = NEW.linked_work_item_id;
            IF NOT FOUND OR target.work_item_id IS NULL OR target.owner_id IS NULL
                OR related.owner_id <> target.owner_id OR related.kind <> 'chore'
                OR (NEW.linked_work_item_id IS DISTINCT FROM target.work_item_id
                    AND related.parent_id IS DISTINCT FROM target.work_item_id) THEN
                RAISE EXCEPTION 'Invalid plan segment link' USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'execution_sessions' THEN
        IF NOT EXISTS (SELECT 1 FROM work_items WHERE id = NEW.work_item_id
                       AND owner_id = NEW.owner_id AND kind IN ('chore', 'sprint'))
            OR NOT EXISTS (SELECT 1 FROM focus_plans WHERE id = NEW.focus_plan_id
                           AND owner_id = NEW.owner_id AND work_item_id = NEW.work_item_id)
            OR (NEW.recommendation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM focus_plan_recommendations WHERE id = NEW.recommendation_id
                AND owner_id = NEW.owner_id AND work_item_id = NEW.work_item_id)) THEN
            RAISE EXCEPTION 'Invalid execution session relationship' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME IN ('session_events', 'session_reviews') THEN
        IF NOT EXISTS (SELECT 1 FROM execution_sessions WHERE id = NEW.session_id
                       AND owner_id = NEW.owner_id) THEN
            RAISE EXCEPTION 'Invalid session record owner' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION taskiller_guard_event_history() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND
        current_setting('taskiller.account_deletion', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Session events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
"""

TABLES = (
    "work_items",
    "focus_plan_recommendations",
    "focus_plans",
    "focus_plan_segments",
    "execution_sessions",
    "session_events",
    "session_reviews",
)


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0003_current_schema_integrity")]
    operations = [
        migrations.RunSQL(
            FORWARD
            + "\n".join(
                f"CREATE TRIGGER tk_{table}_relationships BEFORE INSERT OR UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION taskiller_validate_relationships();"
                for table in TABLES
            )
            + """
            CREATE TRIGGER tk_session_event_history BEFORE UPDATE OR DELETE ON session_events
                FOR EACH ROW EXECUTE FUNCTION taskiller_guard_event_history();
            """,
            reverse_sql="\n".join(
                f"DROP TRIGGER IF EXISTS tk_{table}_relationships ON {table};" for table in TABLES
            )
            + """
            DROP TRIGGER IF EXISTS tk_session_event_history ON session_events;
            DROP FUNCTION IF EXISTS taskiller_guard_event_history();
            DROP FUNCTION IF EXISTS taskiller_validate_relationships();
            """,
        ),
    ]
