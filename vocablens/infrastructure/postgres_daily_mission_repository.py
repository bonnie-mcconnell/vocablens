from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import DailyMissionORM


class PostgresDailyMissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self, limit: int | None = None):
        query = select(DailyMissionORM).order_by(
            DailyMissionORM.mission_date.desc(),
            DailyMissionORM.id.desc(),
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_user_date(self, user_id: int, mission_date: str):
        result = await self.session.execute(
            select(DailyMissionORM).where(
                DailyMissionORM.user_id == user_id,
                DailyMissionORM.mission_date == mission_date,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        mission_date: str,
        weak_area: str,
        mission_max_sessions: int,
        steps: list[dict],
        loss_aversion_message: str,
        streak_at_issue: int,
        momentum_score: float,
        notification_preview: dict,
    ):
        now = utc_now()
        try:
            result = await self.session.execute(
                insert(DailyMissionORM)
                .values(
                    user_id=user_id,
                    mission_date=mission_date,
                    weak_area=weak_area,
                    mission_max_sessions=mission_max_sessions,
                    steps=list(steps),
                    loss_aversion_message=loss_aversion_message,
                    streak_at_issue=streak_at_issue,
                    momentum_score=momentum_score,
                    notification_preview=dict(notification_preview),
                    created_at=now,
                    updated_at=now,
                )
                .returning(DailyMissionORM)
            )
            return result.scalar_one()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_user_date(user_id, mission_date)
            if existing is None:
                raise
            return existing

    async def mark_completed(self, mission_id: int, *, completed_at):
        await self.session.execute(
            update(DailyMissionORM)
            .where(DailyMissionORM.id == mission_id)
            .values(
                status="completed",
                completed_at=completed_at,
                updated_at=utc_now(),
            )
        )
        result = await self.session.execute(
            select(DailyMissionORM).where(DailyMissionORM.id == mission_id)
        )
        return result.scalar_one()
