from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.domain.models import DecisionTrace
from vocablens.infrastructure.db.models import DecisionTraceORM


def _map_row(row: DecisionTraceORM) -> DecisionTrace:
    return DecisionTrace(
        id=int(row.id),
        user_id=int(row.user_id),
        trace_type=str(row.trace_type),
        source=str(row.source),
        reference_id=row.reference_id,
        policy_version=str(row.policy_version),
        inputs=dict(row.inputs or {}),
        outputs=dict(row.outputs or {}),
        reason=row.reason,
        created_at=row.created_at,
    )


class PostgresDecisionTraceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        trace_type: str,
        source: str,
        reference_id: str | None,
        policy_version: str,
        inputs: dict,
        outputs: dict,
        reason: str | None = None,
    ) -> DecisionTrace:
        result = await self.session.execute(
            insert(DecisionTraceORM)
            .values(
                user_id=user_id,
                trace_type=trace_type,
                source=source,
                reference_id=reference_id,
                policy_version=policy_version,
                inputs=dict(inputs),
                outputs=dict(outputs),
                reason=reason,
            )
            .returning(DecisionTraceORM)
        )
        return _map_row(result.scalar_one())

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        trace_type: str | None = None,
        reference_id: str | None = None,
        limit: int = 100,
    ) -> list[DecisionTrace]:
        query = select(DecisionTraceORM).order_by(
            DecisionTraceORM.created_at.desc(),
            DecisionTraceORM.id.desc(),
        ).limit(limit)
        if user_id is not None:
            query = query.where(DecisionTraceORM.user_id == user_id)
        if trace_type:
            query = query.where(DecisionTraceORM.trace_type == trace_type)
        if reference_id:
            query = query.where(DecisionTraceORM.reference_id == reference_id)
        result = await self.session.execute(query)
        return [_map_row(row) for row in result.scalars().all()]
