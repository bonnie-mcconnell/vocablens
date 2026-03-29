from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import OutboxEventORM


class PostgresOutboxEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, *, user_id: int, dedupe_key: str, event_type: str, payload: dict) -> OutboxEventORM:
        row = OutboxEventORM(
            user_id=user_id,
            dedupe_key=dedupe_key,
            event_type=event_type,
            payload=payload,
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def claim_unpublished(
        self,
        *,
        limit: int,
        lock_mode: str = "for_update_skip_locked",
        order_by: str = "id",
    ) -> list[dict]:
        stmt = (
            select(
                OutboxEventORM.id,
                OutboxEventORM.event_type,
                OutboxEventORM.payload,
                OutboxEventORM.dedupe_key,
            )
            .where(OutboxEventORM.published_at.is_(None))
            .order_by(OutboxEventORM.id)
            .limit(limit)
        )
        if lock_mode == "for_update_skip_locked":
            stmt = stmt.with_for_update(skip_locked=True)
        result = await self.session.execute(stmt)
        rows = []
        for row in result.all():
            rows.append(
                {
                    "id": int(row.id),
                    "event_type": str(row.event_type),
                    "payload": dict(row.payload or {}),
                    "dedupe_key": str(row.dedupe_key),
                }
            )
        return rows

    async def mark_published_many(self, *, ids: list[int], published_at=None) -> None:
        if not ids:
            return
        await self.session.execute(
            update(OutboxEventORM)
            .where(OutboxEventORM.id.in_(ids))
            .values(published_at=published_at or utc_now())
        )

    async def increment_retry_many(self, *, ids: list[int]) -> None:
        if not ids:
            return
        await self.session.execute(
            update(OutboxEventORM)
            .where(OutboxEventORM.id.in_(ids))
            .values(retry_count=OutboxEventORM.retry_count + 1)
        )
