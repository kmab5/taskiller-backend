"""Fix execution snapshot comparison semantics."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0007"
down_revision: str | None = "20260928_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FIXED_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_execution_session_references()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  wi_owner uuid;
  wi_kind text;
  fp_owner uuid;
  fp_work uuid;
  fp_template boolean;
  fp_deleted timestamptz;
  rec_owner uuid;
  rec_work uuid;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF (
      NEW.owner_id <> OLD.owner_id OR
      NEW.work_item_id <> OLD.work_item_id OR
      NEW.focus_plan_id <> OLD.focus_plan_id OR
      NEW.recommendation_id IS DISTINCT FROM OLD.recommendation_id OR
      NEW.plan_snapshot_json::jsonb IS DISTINCT FROM
        OLD.plan_snapshot_json::jsonb OR
      NEW.recommendation_snapshot_json::jsonb IS DISTINCT FROM
        OLD.recommendation_snapshot_json::jsonb OR
      NEW.work_context_snapshot_json::jsonb IS DISTINCT FROM
        OLD.work_context_snapshot_json::jsonb OR
      NEW.session_started_at <> OLD.session_started_at OR
      NEW.created_at <> OLD.created_at
    ) THEN
      RAISE EXCEPTION 'execution session identity and snapshots are immutable';
    END IF;
    IF OLD.state IN ('completed', 'abandoned') AND NEW.state <> OLD.state THEN
      RAISE EXCEPTION 'terminal execution session state is immutable';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
      RAISE EXCEPTION 'execution session version must increment by one';
    END IF;
    RETURN NEW;
  END IF;

  SELECT owner_id, kind INTO wi_owner, wi_kind
  FROM work_items
  WHERE id = NEW.work_item_id AND deleted_at IS NULL;
  IF NOT FOUND
     OR wi_owner <> NEW.owner_id
     OR wi_kind NOT IN ('chore', 'sprint') THEN
    RAISE EXCEPTION 'invalid execution session work item reference';
  END IF;

  SELECT owner_id, work_item_id, is_template, deleted_at
  INTO fp_owner, fp_work, fp_template, fp_deleted
  FROM focus_plans
  WHERE id = NEW.focus_plan_id;
  IF NOT FOUND
     OR fp_owner <> NEW.owner_id
     OR fp_work <> NEW.work_item_id
     OR fp_template
     OR fp_deleted IS NOT NULL THEN
    RAISE EXCEPTION 'invalid execution session focus plan reference';
  END IF;

  IF NEW.recommendation_id IS NOT NULL THEN
    SELECT owner_id, work_item_id INTO rec_owner, rec_work
    FROM focus_plan_recommendations
    WHERE id = NEW.recommendation_id;
    IF NOT FOUND
       OR rec_owner <> NEW.owner_id
       OR rec_work <> NEW.work_item_id THEN
      RAISE EXCEPTION 'invalid execution session recommendation reference';
    END IF;
  END IF;
  RETURN NEW;
END;
$$
"""


_OLD_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_execution_session_references()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  wi_owner uuid;
  wi_kind text;
  fp_owner uuid;
  fp_work uuid;
  fp_template boolean;
  fp_deleted timestamptz;
  rec_owner uuid;
  rec_work uuid;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF (
      NEW.owner_id <> OLD.owner_id OR
      NEW.work_item_id <> OLD.work_item_id OR
      NEW.focus_plan_id <> OLD.focus_plan_id OR
      NEW.recommendation_id IS DISTINCT FROM OLD.recommendation_id OR
      NEW.plan_snapshot_json IS DISTINCT FROM OLD.plan_snapshot_json OR
      NEW.recommendation_snapshot_json IS DISTINCT FROM
        OLD.recommendation_snapshot_json OR
      NEW.work_context_snapshot_json IS DISTINCT FROM
        OLD.work_context_snapshot_json OR
      NEW.session_started_at <> OLD.session_started_at OR
      NEW.created_at <> OLD.created_at
    ) THEN
      RAISE EXCEPTION 'execution session identity and snapshots are immutable';
    END IF;
    IF OLD.state IN ('completed', 'abandoned') AND NEW.state <> OLD.state THEN
      RAISE EXCEPTION 'terminal execution session state is immutable';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
      RAISE EXCEPTION 'execution session version must increment by one';
    END IF;
    RETURN NEW;
  END IF;

  SELECT owner_id, kind INTO wi_owner, wi_kind
  FROM work_items
  WHERE id = NEW.work_item_id AND deleted_at IS NULL;
  IF NOT FOUND
     OR wi_owner <> NEW.owner_id
     OR wi_kind NOT IN ('chore', 'sprint') THEN
    RAISE EXCEPTION 'invalid execution session work item reference';
  END IF;

  SELECT owner_id, work_item_id, is_template, deleted_at
  INTO fp_owner, fp_work, fp_template, fp_deleted
  FROM focus_plans
  WHERE id = NEW.focus_plan_id;
  IF NOT FOUND
     OR fp_owner <> NEW.owner_id
     OR fp_work <> NEW.work_item_id
     OR fp_template
     OR fp_deleted IS NOT NULL THEN
    RAISE EXCEPTION 'invalid execution session focus plan reference';
  END IF;

  IF NEW.recommendation_id IS NOT NULL THEN
    SELECT owner_id, work_item_id INTO rec_owner, rec_work
    FROM focus_plan_recommendations
    WHERE id = NEW.recommendation_id;
    IF NOT FOUND
       OR rec_owner <> NEW.owner_id
       OR rec_work <> NEW.work_item_id THEN
      RAISE EXCEPTION 'invalid execution session recommendation reference';
    END IF;
  END IF;
  RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(sa.text(_FIXED_FUNCTION))


def downgrade() -> None:
    op.execute(sa.text(_OLD_FUNCTION))
