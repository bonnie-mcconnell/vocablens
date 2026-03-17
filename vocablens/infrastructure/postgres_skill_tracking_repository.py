import asyncio
from datetime import datetime
from typing import Dict

from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import SkillTrackingORM


class PostgresSkillTrackingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def record(self, user_id: int, skill: str, score: float, created_at: datetime | None = None) -> None:
        await self.session.execute(
            insert(SkillTrackingORM).values(
                user_id=user_id,
                skill=skill,
                score=score,
                created_at=created_at or datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def latest_scores(self, user_id: int) -> Dict[str, float]:
        result = await self.session.execute(
            select(SkillTrackingORM)
            .where(SkillTrackingORM.user_id == user_id)
            .order_by(SkillTrackingORM.created_at.desc())
        )
        scores: Dict[str, float] = {}
        for row in result.scalars():
            if row.skill not in scores:
                scores[row.skill] = row.score
        return scores
