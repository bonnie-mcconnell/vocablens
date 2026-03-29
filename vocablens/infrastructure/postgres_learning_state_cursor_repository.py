from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.domain.models import LearningStateCursor
from vocablens.infrastructure.db.models import LearningStateCursorORM


def _map_row(row: LearningStateCursorORM) -> LearningStateCursor:
    return LearningStateCursor(
        user_id=int(row.user_id),
        last_processed_attempt_id=int(row.last_processed_attempt_id or 0),
    )


class PostgresLearningStateCursorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: int) -> LearningStateCursor:
        result = await self.session.execute(
            select(LearningStateCursorORM).where(LearningStateCursorORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self.session.execute(
                insert(LearningStateCursorORM).values(user_id=user_id, last_processed_attempt_id=0)
            )
            await self.session.flush()
            result = await self.session.execute(
                select(LearningStateCursorORM).where(LearningStateCursorORM.user_id == user_id)
            )
            row = result.scalar_one()
        return _map_row(row)

    async def update(self, user_id: int, *, last_processed_attempt_id: int) -> LearningStateCursor:
        await self.session.execute(
            update(LearningStateCursorORM)
            .where(LearningStateCursorORM.user_id == user_id)
            .values(last_processed_attempt_id=int(last_processed_attempt_id))
        )
        result = await self.session.execute(
            select(LearningStateCursorORM).where(LearningStateCursorORM.user_id == user_id)
        )
        return _map_row(result.scalar_one())
