"""Preserve the original Taskiller v1 built-in Work Types on Django databases."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from django.db import migrations

# Original identifiers and characteristics from Alembic 20260928_0002_work_model.
SYSTEM_TYPES = (
    ("e3d3e891-8760-4b08-8696-ad0fbc7292fd", "study_learning", "Study / Learning", "Learning new material.", "high", "medium", "medium", "low", "sedentary", "acquisition"),
    ("3d4f906a-8d02-4915-9400-7e9d5108ce53", "reading", "Reading", "Focused reading or review of written material.", "medium", "medium", "medium", "low", "sedentary", "acquisition"),
    ("ec4ea345-eba5-4af9-84bf-799b0a151fc3", "writing", "Writing", "Drafting or revising written material.", "high", "high", "high", "low", "sedentary", "none"),
    ("f3b8f3f9-1ec6-4185-8901-d2e87dc3b059", "programming", "Programming", "Software implementation and debugging.", "high", "high", "high", "low", "sedentary", "none"),
    ("ec12f3fa-9770-446a-acfd-78be78e47c2b", "problem_solving", "Problem Solving", "Analytical problems, exercises, or technical reasoning.", "high", "high", "high", "low", "sedentary", "practice"),
    ("2c966900-f837-4c3f-a96e-407c40ec92d4", "creative_generation", "Creative Generation", "Open-ended creative production.", "high", "high", "high", "low", "sedentary", "none"),
    ("6407c9c8-65df-4d7b-a25d-41de06a86700", "brainstorming_planning", "Brainstorming / Planning", "Idea generation, structuring, and planning.", "high", "medium", "medium", "low", "sedentary", "none"),
    ("b075afca-77ad-4361-a203-c3e3f1f43d4c", "administration", "Administration", "Forms, organization, routine management work.", "medium", "low", "low", "high", "sedentary", "none"),
    ("39c7a56a-d72a-4ad1-b95d-95e434c7a5f3", "communication", "Communication", "Email, messages, calls, and coordination.", "medium", "low", "low", "medium", "sedentary", "none"),
    ("9f49e1f5-13d8-4132-a87f-0d29f69a6399", "repetitive_processing", "Repetitive Processing", "Repeated low-context processing work.", "medium", "low", "low", "high", "sedentary", "none"),
    ("520f715c-672e-4795-a7d1-7ff84bd2dc2b", "physical_chore", "Physical Chore", "Physical or household/personal execution work.", "low", "low", "low", "medium", "active", "none"),
)


def seed_system_work_types(apps, schema_editor):
    WorkType = apps.get_model("django_domain", "WorkType")
    db = schema_editor.connection.alias
    now = datetime.now(timezone.utc)
    for (id_text, slug, name, description, cognitive, interruption, continuity, repetitive, physical, learning) in SYSTEM_TYPES:
        uid = UUID(id_text)
        existing = WorkType.objects.using(db).filter(id=uid).first()
        if existing is not None:
            if existing.owner_id is not None or existing.slug != slug or not existing.is_system:
                raise RuntimeError(f"Built-in Work Type ID conflict: {slug} ({uid})")
            continue
        if WorkType.objects.using(db).filter(owner_id__isnull=True, slug__iexact=slug).exists():
            raise RuntimeError(f"Built-in Work Type slug conflict: {slug}")
        WorkType.objects.using(db).create(
            id=uid,
            owner_id=None,
            slug=slug,
            display_name=name,
            description=description,
            cognitive_demand=cognitive,
            interruption_sensitivity=interruption,
            continuity_need=continuity,
            repetitiveness=repetitive,
            physicality=physical,
            learning_mode=learning,
            is_system=True,
            created_at=now,
            updated_at=now,
            version=1,
        )


class Migration(migrations.Migration):
    dependencies = [("django_domain", "0001_existing_schema_baseline")]
    operations = [migrations.RunPython(seed_system_work_types, reverse_code=migrations.RunPython.noop)]
