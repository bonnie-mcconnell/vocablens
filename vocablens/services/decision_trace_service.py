from __future__ import annotations

from vocablens.infrastructure.unit_of_work import UnitOfWork


class DecisionTraceService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        trace_type: str | None = None,
        reference_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            traces = await uow.decision_traces.list_recent(
                user_id=user_id,
                trace_type=trace_type,
                reference_id=reference_id,
                limit=normalized_limit,
            )
            await uow.commit()

        return {
            "traces": [
                {
                    "id": trace.id,
                    "user_id": trace.user_id,
                    "trace_type": trace.trace_type,
                    "source": trace.source,
                    "reference_id": trace.reference_id,
                    "policy_version": trace.policy_version,
                    "inputs": trace.inputs,
                    "outputs": trace.outputs,
                    "reason": trace.reason,
                    "created_at": trace.created_at.isoformat(),
                }
                for trace in traces
            ]
        }
