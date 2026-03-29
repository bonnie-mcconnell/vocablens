from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import UserCoreState
from vocablens.infrastructure.db.models import UserCoreStateORM


def _map_row(row: UserCoreStateORM) -> UserCoreState:
    return UserCoreState(
        user_id=row.user_id,
        xp=int(row.xp or 0),
        level=int(row.level or 1),
        current_streak=int(row.current_streak or 0),
        longest_streak=int(row.longest_streak or 0),
        momentum_score=float(row.momentum_score or 0.0),
        total_sessions=int(row.total_sessions or 0),
        sessions_last_3_days=int(row.sessions_last_3_days or 0),
        version=int(row.version or 1),
        updated_at=row.updated_at,
    )


class PostgresUserCoreStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: int) -> UserCoreState:
        result = await self.session.execute(
            select(UserCoreStateORM).where(UserCoreStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self.session.execute(insert(UserCoreStateORM).values(user_id=user_id))
            await self.session.flush()
            result = await self.session.execute(
                select(UserCoreStateORM).where(UserCoreStateORM.user_id == user_id)
            )
            row = result.scalar_one()
        return _map_row(row)

    async def get_for_update(self, user_id: int) -> UserCoreState:
        await self.get_or_create(user_id)
        result = await self.session.execute(
            select(UserCoreStateORM)
            .where(UserCoreStateORM.user_id == user_id)
            .with_for_update()
        )
        row = result.scalar_one()
        return _map_row(row)

    async def update(self, user_id: int, state: UserCoreState) -> UserCoreState:
        await self.session.execute(
            update(UserCoreStateORM)
            .where(UserCoreStateORM.user_id == user_id)
            .values(
                xp=int(state.xp),
                level=int(state.level),
                current_streak=int(state.current_streak),
                longest_streak=int(state.longest_streak),
                momentum_score=float(state.momentum_score),
                total_sessions=int(state.total_sessions),
                sessions_last_3_days=int(state.sessions_last_3_days),
                version=int(state.version),
                updated_at=utc_now(),
            )
        )
        result = await self.session.execute(
            select(UserCoreStateORM).where(UserCoreStateORM.user_id == user_id)
        )
        return _map_row(result.scalar_one())

    async def get(self, user_id: int) -> UserCoreState | None:
        result = await self.session.execute(
            select(UserCoreStateORM).where(UserCoreStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _map_row(row)
