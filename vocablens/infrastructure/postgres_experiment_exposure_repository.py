from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ExperimentExposureORM


class PostgresExperimentExposureRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentExposureORM).where(
                ExperimentExposureORM.user_id == user_id,
                ExperimentExposureORM.experiment_key == experiment_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_once(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        exposed_at=None,
    ):
        exposure = ExperimentExposureORM(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            exposed_at=exposed_at or utc_now(),
        )
        self.session.add(exposure)
        try:
            await self.session.flush()
            return exposure, True
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get(user_id, experiment_key)
            if existing is None:
                raise
            return existing, False

    async def list_all(self, experiment_key: str | None = None):
        query = select(ExperimentExposureORM).order_by(
            ExperimentExposureORM.experiment_key.asc(),
            ExperimentExposureORM.exposed_at.asc(),
            ExperimentExposureORM.user_id.asc(),
        )
        if experiment_key is not None:
            query = query.where(ExperimentExposureORM.experiment_key == experiment_key)
        result = await self.session.execute(query)
        return result.scalars().all()
