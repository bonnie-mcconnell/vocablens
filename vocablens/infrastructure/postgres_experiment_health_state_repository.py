from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ExperimentHealthStateORM


class PostgresExperimentHealthStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentHealthStateORM).where(ExperimentHealthStateORM.experiment_key == experiment_key)
        )
        return result.scalar_one_or_none()

    async def list_all(self):
        result = await self.session.execute(
            select(ExperimentHealthStateORM).order_by(ExperimentHealthStateORM.experiment_key.asc())
        )
        return result.scalars().all()

    async def upsert(
        self,
        *,
        experiment_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict,
    ):
        row = await self.get(experiment_key)
        now = utc_now()
        if row is None:
            row = ExperimentHealthStateORM(
                experiment_key=experiment_key,
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
