from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import UserLearningState
from vocablens.infrastructure.db.models import UserLearningStateORM


def _map_row(row: UserLearningStateORM) -> UserLearningState:
    return UserLearningState(
        user_id=row.user_id,
        skills=dict(row.skills or {}),
        weak_areas=list(row.weak_areas or []),
        mastery_percent=float(row.mastery_percent or 0.0),
        accuracy_rate=float(row.accuracy_rate or 0.0),
        response_speed_seconds=float(row.response_speed_seconds or 0.0),
        updated_at=row.updated_at,
    )


class PostgresUserLearningStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: int) -> UserLearningState:
        result = await self.session.execute(
            select(UserLearningStateORM).where(UserLearningStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self.session.execute(insert(UserLearningStateORM).values(user_id=user_id))
            await self.session.flush()
            result = await self.session.execute(
                select(UserLearningStateORM).where(UserLearningStateORM.user_id == user_id)
            )
            row = result.scalar_one()
        return _map_row(row)

    async def update(
        self,
        user_id: int,
        *,
        skills: dict[str, float] | None = None,
        weak_areas: list[str] | None = None,
        mastery_percent: float | None = None,
        accuracy_rate: float | None = None,
        response_speed_seconds: float | None = None,
    ) -> UserLearningState:
        await self.get_or_create(user_id)
        values: dict[str, object] = {"updated_at": utc_now()}
        if skills is not None:
            values["skills"] = {key: float(value) for key, value in skills.items()}
        if weak_areas is not None:
            values["weak_areas"] = list(weak_areas)
        if mastery_percent is not None:
            values["mastery_percent"] = float(mastery_percent)
        if accuracy_rate is not None:
            values["accuracy_rate"] = float(accuracy_rate)
        if response_speed_seconds is not None:
            values["response_speed_seconds"] = float(response_speed_seconds)
        await self.session.execute(
            update(UserLearningStateORM)
            .where(UserLearningStateORM.user_id == user_id)
            .values(**values)
        )
        result = await self.session.execute(
            select(UserLearningStateORM).where(UserLearningStateORM.user_id == user_id)
        )
        return _map_row(result.scalar_one())
