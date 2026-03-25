from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import NotificationSuppressionEventORM


class PostgresNotificationSuppressionEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        event_type: str,
        source: str,
        reference_id: str | None,
        policy_key: str | None,
        policy_version: str | None,
        lifecycle_stage: str | None,
        suppression_reason: str | None,
        suppressed_until,
        payload: dict,
        created_at=None,
    ):
        row = NotificationSuppressionEventORM(
            user_id=user_id,
            event_type=event_type,
            source=source,
            reference_id=reference_id,
            policy_key=policy_key,
            policy_version=policy_version,
            lifecycle_stage=lifecycle_stage,
            suppression_reason=suppression_reason,
            suppressed_until=suppressed_until,
            payload=dict(payload or {}),
            created_at=created_at or utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_by_user(self, user_id: int, limit: int = 50):
        result = await self.session.execute(
            select(NotificationSuppressionEventORM)
            .where(NotificationSuppressionEventORM.user_id == user_id)
            .order_by(NotificationSuppressionEventORM.created_at.desc(), NotificationSuppressionEventORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_policy(self, policy_key: str, limit: int = 100):
        result = await self.session.execute(
            select(NotificationSuppressionEventORM)
            .where(NotificationSuppressionEventORM.policy_key == policy_key)
            .order_by(NotificationSuppressionEventORM.created_at.desc(), NotificationSuppressionEventORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()
