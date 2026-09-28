"""Snapshot work context required for stable historical analytics."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0005"
down_revision: str | None = "20260928_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_sessions",
        sa.Column("work_context_snapshot_json", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH RECURSIVE ancestry AS (
              SELECT id AS child_id, parent_id AS ancestor_id, 1 AS depth
              FROM work_items
              WHERE parent_id IS NOT NULL
              UNION ALL
              SELECT a.child_id, parent.parent_id, a.depth + 1
              FROM ancestry AS a
              JOIN work_items AS parent ON parent.id = a.ancestor_id
              WHERE parent.parent_id IS NOT NULL
            ),
            ancestor_json AS (
              SELECT child_id, json_agg(ancestor_id ORDER BY depth) AS ancestor_ids
              FROM ancestry
              GROUP BY child_id
            ),
            linked_ids AS (
              SELECT DISTINCT
                es.id AS session_id,
                CAST(segment ->> 'linkedWorkItemId' AS uuid) AS work_item_id
              FROM execution_sessions AS es
              CROSS JOIN LATERAL json_array_elements(
                es.plan_snapshot_json -> 'segments'
              ) AS segment
              WHERE segment ->> 'linkedWorkItemId' IS NOT NULL
            ),
            linked_context AS (
              SELECT
                li.session_id,
                json_object_agg(
                  li.work_item_id::text,
                  json_build_object(
                    'id', linked.id,
                    'kind', linked.kind,
                    'parentId', linked.parent_id,
                    'ancestorIds', COALESCE(laj.ancestor_ids, '[]'::json),
                    'workTypeId', linked.work_type_id,
                    'workTypeSlug', linked_type.slug,
                    'estimatedEffortSeconds', linked.estimated_effort_seconds,
                    'plannedStartAt', linked.planned_start_at
                  )
                ) AS linked_items
              FROM linked_ids AS li
              JOIN work_items AS linked ON linked.id = li.work_item_id
              LEFT JOIN work_types AS linked_type ON linked_type.id = linked.work_type_id
              LEFT JOIN ancestor_json AS laj ON laj.child_id = linked.id
              GROUP BY li.session_id
            )
            UPDATE execution_sessions AS es
            SET work_context_snapshot_json = json_build_object(
              'capturedAt', es.session_started_at,
              'target', json_build_object(
                'id', wi.id,
                'kind', wi.kind,
                'parentId', wi.parent_id,
                'ancestorIds', COALESCE(aj.ancestor_ids, '[]'::json),
                'workTypeId', wi.work_type_id,
                'workTypeSlug', wt.slug,
                'estimatedEffortSeconds', wi.estimated_effort_seconds,
                'plannedStartAt', wi.planned_start_at
              ),
              'linkedWorkItems', COALESCE(
                (
                  SELECT lc.linked_items
                  FROM linked_context AS lc
                  WHERE lc.session_id = es.id
                ),
                '{}'::json
              )
            )
            FROM work_items AS wi
            LEFT JOIN work_types AS wt ON wt.id = wi.work_type_id
            LEFT JOIN ancestor_json AS aj ON aj.child_id = wi.id
            WHERE wi.id = es.work_item_id
            """
        )
    )
    op.alter_column("execution_sessions", "work_context_snapshot_json", nullable=False)

    op.execute(
        sa.text(
            """
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
              IF NOT FOUND OR wi_owner <> NEW.owner_id OR wi_kind NOT IN ('chore', 'sprint') THEN
                RAISE EXCEPTION 'invalid execution session work item reference';
              END IF;

              SELECT owner_id, work_item_id, is_template, deleted_at
              INTO fp_owner, fp_work, fp_template, fp_deleted
              FROM focus_plans
              WHERE id = NEW.focus_plan_id;
              IF NOT FOUND OR fp_owner <> NEW.owner_id OR fp_work <> NEW.work_item_id
                 OR fp_template OR fp_deleted IS NOT NULL THEN
                RAISE EXCEPTION 'invalid execution session focus plan reference';
              END IF;

              IF NEW.recommendation_id IS NOT NULL THEN
                SELECT owner_id, work_item_id INTO rec_owner, rec_work
                FROM focus_plan_recommendations
                WHERE id = NEW.recommendation_id;
                IF NOT FOUND OR rec_owner <> NEW.owner_id OR rec_work <> NEW.work_item_id THEN
                  RAISE EXCEPTION 'invalid execution session recommendation reference';
                END IF;
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
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
              IF NOT FOUND OR wi_owner <> NEW.owner_id OR wi_kind NOT IN ('chore', 'sprint') THEN
                RAISE EXCEPTION 'invalid execution session work item reference';
              END IF;

              SELECT owner_id, work_item_id, is_template, deleted_at
              INTO fp_owner, fp_work, fp_template, fp_deleted
              FROM focus_plans
              WHERE id = NEW.focus_plan_id;
              IF NOT FOUND OR fp_owner <> NEW.owner_id OR fp_work <> NEW.work_item_id
                 OR fp_template OR fp_deleted IS NOT NULL THEN
                RAISE EXCEPTION 'invalid execution session focus plan reference';
              END IF;

              IF NEW.recommendation_id IS NOT NULL THEN
                SELECT owner_id, work_item_id INTO rec_owner, rec_work
                FROM focus_plan_recommendations
                WHERE id = NEW.recommendation_id;
                IF NOT FOUND OR rec_owner <> NEW.owner_id OR rec_work <> NEW.work_item_id THEN
                  RAISE EXCEPTION 'invalid execution session recommendation reference';
                END IF;
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
    )
    op.drop_column("execution_sessions", "work_context_snapshot_json")
