from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import NotificationPolicyRegistryORM


class PostgresNotificationPolicyRegistryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, policy_key: str):
        result = await self.session.execute(
            select(NotificationPolicyRegistryORM).where(NotificationPolicyRegistryORM.policy_key == policy_key)
        )
        return result.scalar_one_or_none()

    async def list_all(self):
        result = await self.session.execute(
            select(NotificationPolicyRegistryORM).order_by(NotificationPolicyRegistryORM.policy_key.asc())
        )
        return result.scalars().all()

    async def upsert(
        self,
        *,
        policy_key: str,
        status: str,
        is_killed: bool,
        description: str | None,
        policy: dict,
    ):
        row = await self.get(policy_key)
        if row is None:
            row = NotificationPolicyRegistryORM(
                policy_key=policy_key,
                status=status,
                is_killed=is_killed,
                description=description,
                policy=dict(policy or {}),
                updated_at=utc_now(),
            )
            self.session.add(row)
            await self.session.flush()
            return row
        row.status = status
        row.is_killed = is_killed
        row.description = description
        row.policy = dict(policy or {})
        row.updated_at = utc_now()
        await self.session.flush()
        return row
