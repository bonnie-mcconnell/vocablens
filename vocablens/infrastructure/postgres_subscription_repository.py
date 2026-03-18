from vocablens.core.time import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import SubscriptionORM


class PostgresSubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, user_id: int, tier: str, request_limit: int, token_limit: int):
        existing = await self.get_by_user(user_id)
        if existing:
            existing.tier = tier
            existing.request_limit = request_limit
            existing.token_limit = token_limit
            existing.renewed_at = utc_now()
            return existing
        sub = SubscriptionORM(
            user_id=user_id,
            tier=tier,
            request_limit=request_limit,
            token_limit=token_limit,
        )
        self.session.add(sub)
        return sub

    async def get_by_user(self, user_id: int):
        result = await self.session.execute(
            select(SubscriptionORM).where(SubscriptionORM.user_id == user_id)
        )
        return result.scalar_one_or_none()
