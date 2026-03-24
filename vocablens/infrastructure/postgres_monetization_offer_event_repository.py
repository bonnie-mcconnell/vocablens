from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import MonetizationOfferEventORM


class PostgresMonetizationOfferEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        *,
        user_id: int,
        event_type: str,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        payload: dict,
        created_at=None,
    ):
        result = await self.session.execute(
            insert(MonetizationOfferEventORM)
            .values(
                user_id=user_id,
                event_type=event_type,
                offer_type=offer_type,
                paywall_type=paywall_type,
                strategy=strategy,
                geography=geography,
                payload=dict(payload),
                created_at=created_at or utc_now(),
            )
            .returning(MonetizationOfferEventORM)
        )
        return result.scalar_one()

    async def list_by_user(self, user_id: int, limit: int = 100):
        result = await self.session.execute(
            select(MonetizationOfferEventORM)
            .where(MonetizationOfferEventORM.user_id == user_id)
            .order_by(
                MonetizationOfferEventORM.created_at.desc(),
                MonetizationOfferEventORM.id.desc(),
            )
            .limit(limit)
        )
        return result.scalars().all()
