from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import ExperimentRegistryAuditORM


class PostgresExperimentRegistryAuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        experiment_key: str,
        action: str,
        changed_by: str,
        change_note: str,
        previous_config: dict,
        new_config: dict,
    ):
        result = await self.session.execute(
            insert(ExperimentRegistryAuditORM)
            .values(
                experiment_key=experiment_key,
                action=action,
                changed_by=changed_by,
                change_note=change_note,
                previous_config=dict(previous_config),
                new_config=dict(new_config),
            )
            .returning(ExperimentRegistryAuditORM)
        )
        return result.scalar_one()

    async def list_by_experiment(self, experiment_key: str, limit: int = 50):
        result = await self.session.execute(
            select(ExperimentRegistryAuditORM)
            .where(ExperimentRegistryAuditORM.experiment_key == experiment_key)
            .order_by(
                ExperimentRegistryAuditORM.created_at.desc(),
                ExperimentRegistryAuditORM.id.desc(),
            )
            .limit(limit)
        )
        return result.scalars().all()

    async def latest_for_experiment(self, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentRegistryAuditORM)
            .where(ExperimentRegistryAuditORM.experiment_key == experiment_key)
            .order_by(
                ExperimentRegistryAuditORM.created_at.desc(),
                ExperimentRegistryAuditORM.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
