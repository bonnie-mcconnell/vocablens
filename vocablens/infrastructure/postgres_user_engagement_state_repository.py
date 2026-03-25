from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import UserEngagementState
from vocablens.infrastructure.db.models import UserEngagementStateORM


def _map_row(row: UserEngagementStateORM) -> UserEngagementState:
    return UserEngagementState(
        user_id=row.user_id,
        current_streak=int(row.current_streak or 0),
        longest_streak=int(row.longest_streak or 0),
        momentum_score=float(row.momentum_score or 0.0),
        total_sessions=int(row.total_sessions or 0),
        sessions_last_3_days=int(row.sessions_last_3_days or 0),
        last_session_at=row.last_session_at,
        shields_used_this_week=int(row.shields_used_this_week or 0),
        daily_mission_completed_at=row.daily_mission_completed_at,
        interaction_stats=dict(row.interaction_stats or {}),
        updated_at=row.updated_at,
    )


class PostgresUserEngagementStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[UserEngagementState]:
        result = await self.session.execute(
            select(UserEngagementStateORM).order_by(UserEngagementStateORM.user_id.asc())
        )
        return [_map_row(row) for row in result.scalars().all()]

    async def get_or_create(self, user_id: int) -> UserEngagementState:
        result = await self.session.execute(
            select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self.session.execute(insert(UserEngagementStateORM).values(user_id=user_id))
            await self.session.flush()
            result = await self.session.execute(
                select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id)
            )
            row = result.scalar_one()
        return _map_row(row)

    async def update(
        self,
        user_id: int,
        *,
        current_streak: int | None = None,
        longest_streak: int | None = None,
        momentum_score: float | None = None,
        total_sessions: int | None = None,
        sessions_last_3_days: int | None = None,
        last_session_at=None,
        shields_used_this_week: int | None = None,
        daily_mission_completed_at=None,
        interaction_stats: dict[str, int] | None = None,
    ) -> UserEngagementState:
        await self.get_or_create(user_id)
        values: dict[str, object] = {"updated_at": utc_now()}
        if current_streak is not None:
            values["current_streak"] = int(current_streak)
        if longest_streak is not None:
            values["longest_streak"] = int(longest_streak)
        if momentum_score is not None:
            values["momentum_score"] = float(momentum_score)
        if total_sessions is not None:
            values["total_sessions"] = int(total_sessions)
        if sessions_last_3_days is not None:
            values["sessions_last_3_days"] = int(sessions_last_3_days)
        if last_session_at is not None:
            values["last_session_at"] = last_session_at
        if shields_used_this_week is not None:
            values["shields_used_this_week"] = int(shields_used_this_week)
        if daily_mission_completed_at is not None:
            values["daily_mission_completed_at"] = daily_mission_completed_at
        if interaction_stats is not None:
            values["interaction_stats"] = {key: int(value) for key, value in interaction_stats.items()}
        await self.session.execute(
            update(UserEngagementStateORM)
            .where(UserEngagementStateORM.user_id == user_id)
            .values(**values)
        )
        result = await self.session.execute(
            select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id)
        )
        return _map_row(result.scalar_one())
