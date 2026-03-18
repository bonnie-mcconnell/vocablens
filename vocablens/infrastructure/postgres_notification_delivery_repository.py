import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import NotificationDeliveryORM


class PostgresNotificationDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_attempt(
        self,
        *,
        user_id: int,
        category: str,
        provider: str,
        title: str,
        body: str,
        payload: dict | None = None,
    ) -> NotificationDeliveryORM:
        row = NotificationDeliveryORM(
            user_id=user_id,
            category=category,
            provider=provider,
            status="pending",
            title=title,
            body=body,
            payload_json=json.dumps(payload or {}),
            attempt_count=1,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def mark_status(self, delivery_id: int, status: str, error_message: str | None = None) -> None:
        await self.session.execute(
            update(NotificationDeliveryORM)
            .where(NotificationDeliveryORM.id == delivery_id)
            .values(
                status=status,
                error_message=error_message,
                updated_at=utc_now(),
            )
        )

    async def list_recent(self, user_id: int, limit: int = 20):
        result = await self.session.execute(
            select(NotificationDeliveryORM)
            .where(NotificationDeliveryORM.user_id == user_id)
            .order_by(NotificationDeliveryORM.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
