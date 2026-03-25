from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import ExerciseTemplateORM


class PostgresExerciseTemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_key(self, template_key: str):
        result = await self.session.execute(
            select(ExerciseTemplateORM).where(ExerciseTemplateORM.template_key == template_key)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        objectives: list[str] | None = None,
        difficulty: str | None = None,
        limit: int = 20,
    ):
        stmt = select(ExerciseTemplateORM).where(ExerciseTemplateORM.status == "active")
        if objectives:
            stmt = stmt.where(ExerciseTemplateORM.objective.in_(list(objectives)))
        if difficulty:
            stmt = stmt.where(ExerciseTemplateORM.difficulty == difficulty)
        stmt = stmt.order_by(
            ExerciseTemplateORM.objective.asc(),
            ExerciseTemplateORM.difficulty.asc(),
            ExerciseTemplateORM.template_key.asc(),
        ).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
