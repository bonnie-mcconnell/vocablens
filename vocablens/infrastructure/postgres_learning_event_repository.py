import asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.db.models import LearningEventORM


class PostgresLearningEventRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def record(self, user_id: int, event_type: str, payload_json: str):
        async with self._session_factory() as session:
            await session.execute(
                insert(LearningEventORM).values(
                    user_id=user_id,
                    event_type=event_type,
                    payload_json=payload_json,
                )
            )
            await session.commit()

    def record_sync(self, *a, **k):
        return self._run(self.record(*a, **k))
