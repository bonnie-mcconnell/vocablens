from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import ContentQualityCheckORM


class PostgresContentQualityCheckRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        source: str,
        artifact_type: str,
        reference_id: str,
        status: str,
        score: float,
        violations: list[dict],
        artifact_summary: dict,
    ):
        row = ContentQualityCheckORM(
            user_id=user_id,
            source=source,
            artifact_type=artifact_type,
            reference_id=reference_id,
            status=status,
            score=score,
            violations=list(violations or []),
            artifact_summary=dict(artifact_summary or {}),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_recent(self, limit: int = 100):
        result = await self.session.execute(
            select(ContentQualityCheckORM)
            .order_by(ContentQualityCheckORM.checked_at.desc(), ContentQualityCheckORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_since(self, since: datetime, limit: int = 1000):
        result = await self.session.execute(
            select(ContentQualityCheckORM)
            .where(ContentQualityCheckORM.checked_at >= since)
            .order_by(ContentQualityCheckORM.checked_at.desc(), ContentQualityCheckORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()
