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

    async def list_all(self):
        result = await self.session.execute(
            select(ExerciseTemplateORM).order_by(ExerciseTemplateORM.template_key.asc())
        )
        return result.scalars().all()

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

    async def upsert(
        self,
        *,
        template_key: str,
        exercise_type: str,
        objective: str,
        difficulty: str,
        status: str,
        prompt_template: str,
        answer_source: str,
        choice_count: int | None,
        template_metadata: dict,
    ):
        row = await self.get_by_key(template_key)
        if row is None:
            row = ExerciseTemplateORM(
                template_key=template_key,
                exercise_type=exercise_type,
                objective=objective,
                difficulty=difficulty,
                status=status,
                prompt_template=prompt_template,
                answer_source=answer_source,
                choice_count=choice_count,
                template_metadata=dict(template_metadata or {}),
            )
            self.session.add(row)
            await self.session.flush()
            return row
        row.exercise_type = exercise_type
        row.objective = objective
        row.difficulty = difficulty
        row.status = status
        row.prompt_template = prompt_template
        row.answer_source = answer_source
        row.choice_count = choice_count
        row.template_metadata = dict(template_metadata or {})
        await self.session.flush()
        return row
