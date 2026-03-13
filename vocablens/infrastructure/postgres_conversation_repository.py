import asyncio
from datetime import datetime
from sqlalchemy import insert

from vocablens.infrastructure.db.models import ConversationHistoryORM
from vocablens.infrastructure.db.session import AsyncSession


class PostgresConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def save_turn(self, user_id: int, role: str, message: str, created_at: datetime | None = None):
        await self.session.execute(
            insert(ConversationHistoryORM).values(
                user_id=user_id,
                role=role,
                message=message,
                created_at=created_at or datetime.utcnow(),
            )
        )
        await self.session.commit()

    def save_turn_sync(self, *a, **k):
        return self._run(self.save_turn(*a, **k))
