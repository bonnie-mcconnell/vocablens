from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import ExerciseTemplateAuditORM


class PostgresExerciseTemplateAuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        template_key: str,
        action: str,
        changed_by: str,
        change_note: str,
        previous_config: dict,
        new_config: dict,
        fixture_report: dict,
    ):
        row = ExerciseTemplateAuditORM(
            template_key=template_key,
            action=action,
            changed_by=changed_by,
            change_note=change_note,
            previous_config=dict(previous_config or {}),
            new_config=dict(new_config or {}),
            fixture_report=dict(fixture_report or {}),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_by_template(self, template_key: str, limit: int = 50):
        result = await self.session.execute(
            select(ExerciseTemplateAuditORM)
            .where(ExerciseTemplateAuditORM.template_key == template_key)
            .order_by(ExerciseTemplateAuditORM.created_at.desc(), ExerciseTemplateAuditORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def latest_for_template(self, template_key: str):
        result = await self.session.execute(
            select(ExerciseTemplateAuditORM)
            .where(ExerciseTemplateAuditORM.template_key == template_key)
            .order_by(ExerciseTemplateAuditORM.created_at.desc(), ExerciseTemplateAuditORM.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
