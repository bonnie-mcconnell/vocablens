from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import NotificationPolicyAuditORM


class PostgresNotificationPolicyAuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        policy_key: str,
        action: str,
        changed_by: str,
        change_note: str,
        previous_config: dict,
        new_config: dict,
    ):
        row = NotificationPolicyAuditORM(
            policy_key=policy_key,
            action=action,
            changed_by=changed_by,
            change_note=change_note,
            previous_config=dict(previous_config or {}),
            new_config=dict(new_config or {}),
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_by_policy(self, policy_key: str, limit: int = 50):
        result = await self.session.execute(
            select(NotificationPolicyAuditORM)
            .where(NotificationPolicyAuditORM.policy_key == policy_key)
            .order_by(NotificationPolicyAuditORM.created_at.desc(), NotificationPolicyAuditORM.id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def latest_for_policy(self, policy_key: str):
        result = await self.session.execute(
            select(NotificationPolicyAuditORM)
            .where(NotificationPolicyAuditORM.policy_key == policy_key)
            .order_by(NotificationPolicyAuditORM.created_at.desc(), NotificationPolicyAuditORM.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
