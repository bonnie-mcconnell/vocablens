from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import ExperimentAssignmentORM


class PostgresExperimentAssignmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int, experiment_key: str):
        result = await self.session.execute(
            select(ExperimentAssignmentORM).where(
                ExperimentAssignmentORM.user_id == user_id,
                ExperimentAssignmentORM.experiment_key == experiment_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_once(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assigned_at=None,
    ):
        assignment = ExperimentAssignmentORM(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            assigned_at=assigned_at or utc_now(),
        )
        self.session.add(assignment)
        try:
            await self.session.flush()
            return assignment, True
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get(user_id, experiment_key)
            if existing is None:
                raise
            return existing, False

    async def list_all(self, experiment_key: str | None = None):
        query = select(ExperimentAssignmentORM).order_by(
            ExperimentAssignmentORM.experiment_key.asc(),
            ExperimentAssignmentORM.assigned_at.asc(),
            ExperimentAssignmentORM.user_id.asc(),
        )
        if experiment_key is not None:
            query = query.where(ExperimentAssignmentORM.experiment_key == experiment_key)
        result = await self.session.execute(query)
        return result.scalars().all()
