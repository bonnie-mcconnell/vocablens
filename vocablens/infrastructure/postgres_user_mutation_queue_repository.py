from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import UserMutationQueueItem
from vocablens.infrastructure.db.models import UserMutationQueueORM


def _map_row(row: UserMutationQueueORM) -> UserMutationQueueItem:
    return UserMutationQueueItem(
        id=int(row.id),
        user_id=int(row.user_id),
        idempotency_key=str(row.idempotency_key),
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


class PostgresUserMutationQueueRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def count(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(UserMutationQueueORM).where(UserMutationQueueORM.user_id == user_id)
        )
        return int(result.scalar_one())

    async def insert(self, *, user_id: int, idempotency_key: str, payload: dict) -> UserMutationQueueItem:
        row = UserMutationQueueORM(
            user_id=user_id,
            idempotency_key=idempotency_key,
            payload=payload,
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return _map_row(row)

    async def claim_batch(self, *, user_id: int, limit: int) -> list[UserMutationQueueItem]:
        result = await self.session.execute(
            select(UserMutationQueueORM)
            .where(UserMutationQueueORM.user_id == user_id)
            .order_by(UserMutationQueueORM.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_map_row(row) for row in result.scalars().all()]

    async def delete_ids(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.session.execute(
            delete(UserMutationQueueORM).where(UserMutationQueueORM.id.in_(ids))
        )
