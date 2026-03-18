from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ConversationHistoryORM


class PostgresConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_turn(self, user_id: int, role: str, message: str, created_at=None):
        await self.session.execute(
            insert(ConversationHistoryORM).values(
                user_id=user_id,
                role=role,
                message=message,
                created_at=created_at or utc_now(),
            )
        )
        await self.session.commit()
