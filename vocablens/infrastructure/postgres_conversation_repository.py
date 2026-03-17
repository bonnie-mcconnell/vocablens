import asyncio
from datetime import datetime
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.db.models import ConversationHistoryORM


class PostgresConversationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def save_turn(self, user_id: int, role: str, message: str, created_at: datetime | None = None):
        async with self._session_factory() as session:
            await session.execute(
                insert(ConversationHistoryORM).values(
                    user_id=user_id,
                    role=role,
                    message=message,
                    created_at=created_at or datetime.utcnow(),
                )
            )
            await session.commit()

    def save_turn_sync(self, *a, **k):
        return self._run(self.save_turn(*a, **k))
