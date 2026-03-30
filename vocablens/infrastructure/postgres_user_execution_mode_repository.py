from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserExecutionModeORM


class PostgresUserExecutionModeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: int) -> str:
        result = await self.session.execute(
            select(UserExecutionModeORM).where(UserExecutionModeORM.user_id == int(user_id))
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = UserExecutionModeORM(user_id=int(user_id), mode="cold", updated_at=utc_now())
            self.session.add(row)
            await self.session.flush()
        return str(row.mode)

    async def set_mode(self, *, user_id: int, mode: str) -> str:
        normalized = "hot" if str(mode).lower() == "hot" else "cold"
        await self.get_or_create(int(user_id))
        await self.session.execute(
            update(UserExecutionModeORM)
            .where(UserExecutionModeORM.user_id == int(user_id))
            .values(mode=normalized, updated_at=utc_now())
        )
        return normalized
