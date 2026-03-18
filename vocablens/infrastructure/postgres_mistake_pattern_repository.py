from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import MistakePatternORM


class PostgresMistakePatternRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(self, user_id: int, category: str, pattern: str):
        now = utc_now()
        existing = await self.session.execute(
            select(MistakePatternORM).where(
                MistakePatternORM.user_id == user_id,
                MistakePatternORM.category == category,
                MistakePatternORM.pattern == pattern,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            await self.session.execute(
                update(MistakePatternORM)
                .where(MistakePatternORM.id == row.id)
                .values(count=row.count + 1, last_seen_at=now)
            )
        else:
            await self.session.execute(
                insert(MistakePatternORM).values(
                    user_id=user_id,
                    category=category,
                    pattern=pattern,
                    count=1,
                    last_seen_at=now,
                )
            )

    async def top_patterns(self, user_id: int, limit: int = 10):
        result = await self.session.execute(
            select(MistakePatternORM).where(MistakePatternORM.user_id == user_id).order_by(MistakePatternORM.count.desc()).limit(limit)
        )
        return result.scalars().all()

    async def repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 10):
        result = await self.session.execute(
            select(MistakePatternORM)
            .where(
                MistakePatternORM.user_id == user_id,
                MistakePatternORM.count >= threshold,
            )
            .order_by(MistakePatternORM.count.desc(), MistakePatternORM.last_seen_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
