from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import RewardChestORM


class PostgresRewardChestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_mission_id(self, mission_id: int):
        result = await self.session.execute(
            select(RewardChestORM).where(RewardChestORM.mission_id == mission_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        mission_id: int,
        xp_reward: int,
        badge_hint: str,
        payload: dict,
    ):
        now = utc_now()
        result = await self.session.execute(
            insert(RewardChestORM)
            .values(
                user_id=user_id,
                mission_id=mission_id,
                xp_reward=xp_reward,
                badge_hint=badge_hint,
                payload=dict(payload),
                created_at=now,
                updated_at=now,
            )
            .returning(RewardChestORM)
        )
        return result.scalar_one()

    async def mark_unlocked(self, chest_id: int, *, unlocked_at):
        await self.session.execute(
            update(RewardChestORM)
            .where(RewardChestORM.id == chest_id)
            .values(
                status="unlocked",
                unlocked_at=unlocked_at,
                updated_at=utc_now(),
            )
        )
        result = await self.session.execute(
            select(RewardChestORM).where(RewardChestORM.id == chest_id)
        )
        return result.scalar_one()
