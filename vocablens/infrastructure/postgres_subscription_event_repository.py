import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import SubscriptionEventORM


class PostgresSubscriptionEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        *,
        user_id: int,
        event_type: str,
        from_tier: str | None = None,
        to_tier: str | None = None,
        feature_name: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.session.add(
            SubscriptionEventORM(
                user_id=user_id,
                event_type=event_type,
                from_tier=from_tier,
                to_tier=to_tier,
                feature_name=feature_name,
                metadata_json=json.dumps(metadata or {}),
            )
        )

    async def counts_by_event(self):
        result = await self.session.execute(
            select(
                SubscriptionEventORM.event_type,
                func.count(SubscriptionEventORM.id),
            )
            .group_by(SubscriptionEventORM.event_type)
        )
        return {row[0]: int(row[1]) for row in result.all()}
