from __future__ import annotations

from sqlalchemy import desc, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import LifecycleTransitionORM


class PostgresLifecycleTransitionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        from_stage: str | None,
        to_stage: str,
        reasons: list[str],
        source: str,
        reference_id: str | None,
        payload: dict,
        created_at,
    ):
        result = await self.session.execute(
            insert(LifecycleTransitionORM)
            .values(
                user_id=user_id,
                from_stage=from_stage,
                to_stage=to_stage,
                reasons=list(reasons),
                source=source,
                reference_id=reference_id,
                payload=dict(payload),
                created_at=created_at,
            )
            .returning(LifecycleTransitionORM)
        )
        return result.scalar_one()

    async def list_by_user(self, user_id: int, limit: int = 50):
        result = await self.session.execute(
            select(LifecycleTransitionORM)
            .where(LifecycleTransitionORM.user_id == user_id)
            .order_by(desc(LifecycleTransitionORM.created_at), desc(LifecycleTransitionORM.id))
            .limit(limit)
        )
        return result.scalars().all()

    async def list_all(self, limit: int | None = None):
        query = select(LifecycleTransitionORM).order_by(
            desc(LifecycleTransitionORM.created_at),
            desc(LifecycleTransitionORM.id),
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
