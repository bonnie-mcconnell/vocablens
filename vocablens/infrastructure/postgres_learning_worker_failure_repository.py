from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import LearningWorkerFailureORM


class PostgresLearningWorkerFailureRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> dict | None:
        row = await self.session.get(LearningWorkerFailureORM, int(user_id))
        if row is None:
            return None
        return {
            "user_id": int(row.user_id),
            "failure_count": int(row.failure_count),
            "quarantined_until": row.quarantined_until,
            "last_error": row.last_error,
            "updated_at": row.updated_at,
        }

    async def is_quarantined(self, user_id: int) -> bool:
        row = await self.session.get(LearningWorkerFailureORM, int(user_id))
        if row is None or row.quarantined_until is None:
            return False
        return row.quarantined_until > utc_now()

    async def record_failure(self, *, user_id: int, error: str, threshold: int, quarantine_seconds: int) -> dict:
        row = await self.session.get(LearningWorkerFailureORM, int(user_id))
        if row is None:
            row = LearningWorkerFailureORM(user_id=int(user_id), failure_count=0, updated_at=utc_now())
            self.session.add(row)
            await self.session.flush()
        row.failure_count = int(row.failure_count) + 1
        row.last_error = str(error)[:1024]
        row.updated_at = utc_now()
        if int(row.failure_count) >= int(threshold):
            row.quarantined_until = utc_now() + timedelta(seconds=int(quarantine_seconds))
        await self.session.flush()
        return {
            "failure_count": int(row.failure_count),
            "quarantined_until": row.quarantined_until,
        }

    async def clear(self, user_id: int) -> None:
        row = await self.session.get(LearningWorkerFailureORM, int(user_id))
        if row is None:
            return
        row.failure_count = 0
        row.quarantined_until = None
        row.last_error = None
        row.updated_at = utc_now()
        await self.session.flush()
