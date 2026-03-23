from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ExperimentRegistryORM


class PostgresExperimentRegistryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentRegistryORM).where(
                ExperimentRegistryORM.experiment_key == experiment_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self):
        result = await self.session.execute(
            select(ExperimentRegistryORM).order_by(ExperimentRegistryORM.experiment_key.asc())
        )
        return result.scalars().all()

    async def upsert(
        self,
        *,
        experiment_key: str,
        status: str,
        rollout_percentage: int,
        is_killed: bool,
        description: str | None,
        variants: list[dict],
    ):
        existing = await self.get(experiment_key)
        now = utc_now()
        if existing is None:
            existing = ExperimentRegistryORM(
                experiment_key=experiment_key,
                created_at=now,
            )
            self.session.add(existing)
        existing.status = status
        existing.rollout_percentage = rollout_percentage
        existing.is_killed = is_killed
        existing.description = description
        existing.variants = list(variants)
        existing.updated_at = now
        return existing
