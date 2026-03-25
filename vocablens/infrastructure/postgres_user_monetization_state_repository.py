from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserMonetizationStateORM


class PostgresUserMonetizationStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: int):
        result = await self.session.execute(
            select(UserMonetizationStateORM).where(UserMonetizationStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        row = UserMonetizationStateORM(user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, user_id: int, **kwargs):
        row = await self.get_or_create(user_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list_all(self):
        result = await self.session.execute(
            select(UserMonetizationStateORM).order_by(UserMonetizationStateORM.user_id.asc())
        )
        return result.scalars().all()
