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
        holdout_percentage: int,
        is_killed: bool,
        baseline_variant: str,
        description: str | None,
        variants: list[dict],
        eligibility: dict,
        mutually_exclusive_with: list[str],
        prerequisite_experiments: list[str],
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
        existing.holdout_percentage = holdout_percentage
        existing.is_killed = is_killed
        existing.baseline_variant = baseline_variant
        existing.description = description
        existing.variants = list(variants)
        existing.eligibility = dict(eligibility)
        existing.mutually_exclusive_with = list(mutually_exclusive_with)
        existing.prerequisite_experiments = list(prerequisite_experiments)
        existing.updated_at = now
        return existing
