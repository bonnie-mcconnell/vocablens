from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ExperimentOutcomeAttributionORM


class PostgresExperimentOutcomeAttributionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentOutcomeAttributionORM).where(
                ExperimentOutcomeAttributionORM.user_id == user_id,
                ExperimentOutcomeAttributionORM.experiment_key == experiment_key,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assignment_reason: str,
        attribution_version: str,
        exposed_at: datetime,
        window_end_at: datetime,
    ):
        row = ExperimentOutcomeAttributionORM(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            assignment_reason=assignment_reason,
            attribution_version=attribution_version,
            exposed_at=exposed_at,
            window_end_at=window_end_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, user_id: int, experiment_key: str, **kwargs):
        row = await self.get(user_id, experiment_key)
        if row is None:
            raise RuntimeError(f"Experiment outcome attribution missing for '{experiment_key}'")
        for key, value in kwargs.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list_all(self, experiment_key: str | None = None):
        query = select(ExperimentOutcomeAttributionORM).order_by(
            ExperimentOutcomeAttributionORM.experiment_key.asc(),
            ExperimentOutcomeAttributionORM.exposed_at.asc(),
            ExperimentOutcomeAttributionORM.user_id.asc(),
        )
        if experiment_key is not None:
            query = query.where(ExperimentOutcomeAttributionORM.experiment_key == experiment_key)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_active_by_user(self, user_id: int, occurred_at: datetime):
        result = await self.session.execute(
            select(ExperimentOutcomeAttributionORM)
            .where(
                ExperimentOutcomeAttributionORM.user_id == user_id,
                ExperimentOutcomeAttributionORM.exposed_at <= occurred_at,
                ExperimentOutcomeAttributionORM.window_end_at >= occurred_at,
            )
            .order_by(
                ExperimentOutcomeAttributionORM.exposed_at.asc(),
                ExperimentOutcomeAttributionORM.experiment_key.asc(),
            )
        )
        return result.scalars().all()
