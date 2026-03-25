from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import NotificationPolicyHealthStateORM


class PostgresNotificationPolicyHealthStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, policy_key: str):
        result = await self.session.execute(
            select(NotificationPolicyHealthStateORM).where(NotificationPolicyHealthStateORM.policy_key == policy_key)
        )
        return result.scalar_one_or_none()

    async def list_all(self):
        result = await self.session.execute(
            select(NotificationPolicyHealthStateORM).order_by(NotificationPolicyHealthStateORM.policy_key.asc())
        )
        return result.scalars().all()

    async def upsert(
        self,
        *,
        policy_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict,
    ):
        row = await self.get(policy_key)
        now = utc_now()
        if row is None:
            row = NotificationPolicyHealthStateORM(
                policy_key=policy_key,
                current_status=current_status,
                latest_alert_codes=list(latest_alert_codes),
                metrics=dict(metrics or {}),
                last_evaluated_at=now,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        row.current_status = current_status
        row.latest_alert_codes = list(latest_alert_codes)
        row.metrics = dict(metrics or {})
        row.last_evaluated_at = now
        await self.session.flush()
        return row
