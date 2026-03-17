import asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import LearningEventORM


class PostgresLearningEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def record(self, user_id: int, event_type: str, payload_json: str):
        await self.session.execute(
            insert(LearningEventORM).values(
                user_id=user_id,
                event_type=event_type,
                payload_json=payload_json,
            )
        )
        await self.session.commit()
