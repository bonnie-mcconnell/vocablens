from datetime import date
from typing import Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UsageLogORM


class PostgresUsageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(self, user_id: int, endpoint: str, tokens: int, success: bool = True) -> None:
        entry = UsageLogORM(
            user_id=user_id,
            endpoint=endpoint,
            tokens_used=tokens,
            success=success,
        )
        self.session.add(entry)

    async def totals_for_user_day(self, user_id: int, day: date | None = None) -> Tuple[int, int]:
        day = day or utc_now().date()
        result = await self.session.execute(
            select(
                func.count(UsageLogORM.id),
                func.coalesce(func.sum(UsageLogORM.tokens_used), 0),
            ).where(
                UsageLogORM.user_id == user_id,
                func.date(UsageLogORM.created_at) == day,
            )
        )
        counts = result.one_or_none()
        if not counts:
            return (0, 0)
        return int(counts[0]), int(counts[1] or 0)
