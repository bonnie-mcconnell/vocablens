from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserLifecycleStateORM


class PostgresUserLifecycleStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int):
        result = await self.session.execute(
            select(UserLifecycleStateORM).where(UserLifecycleStateORM.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        current_stage: str,
        previous_stage: str | None,
        current_reasons: list[str],
        entered_at,
        last_transition_at,
        last_transition_source: str,
        last_transition_reference_id: str | None,
        transition_count: int,
    ):
        row = UserLifecycleStateORM(
            user_id=user_id,
            current_stage=current_stage,
            previous_stage=previous_stage,
            current_reasons=list(current_reasons),
            entered_at=entered_at,
            last_transition_at=last_transition_at,
            last_transition_source=last_transition_source,
            last_transition_reference_id=last_transition_reference_id,
            transition_count=transition_count,
            updated_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, user_id: int, **kwargs):
        row = await self.get(user_id)
        if row is None:
            raise ValueError(f"Lifecycle state not found for user_id={user_id}")
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row
