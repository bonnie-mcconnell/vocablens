from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class LifecycleStateWriteResult:
    state: Any
    changed: bool
    transition: Any | None


class LifecycleStateService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def record_stage(
        self,
        *,
        user_id: int,
        stage: str,
        reasons: list[str],
        source: str,
        reference_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> LifecycleStateWriteResult:
        now = utc_now()
        transition_payload = dict(payload or {})
        normalized_reasons = [str(reason) for reason in reasons]

        async with self._uow_factory() as uow:
            state = await uow.lifecycle_states.get(user_id)
            transition = None
            changed = False

            if state is None:
                state = await uow.lifecycle_states.create(
                    user_id=user_id,
                    current_stage=stage,
                    previous_stage=None,
                    current_reasons=normalized_reasons,
                    entered_at=now,
                    last_transition_at=now,
                    last_transition_source=source,
                    last_transition_reference_id=reference_id,
                    transition_count=1,
                )
                transition = await uow.lifecycle_transitions.create(
                    user_id=user_id,
                    from_stage=None,
                    to_stage=stage,
                    reasons=normalized_reasons,
                    source=source,
                    reference_id=reference_id,
                    payload=transition_payload,
                    created_at=now,
                )
                changed = True
            elif str(state.current_stage) != stage:
                previous_stage = str(state.current_stage)
                state = await uow.lifecycle_states.update(
                    user_id,
                    current_stage=stage,
                    previous_stage=previous_stage,
                    current_reasons=normalized_reasons,
                    entered_at=now,
                    last_transition_at=now,
                    last_transition_source=source,
                    last_transition_reference_id=reference_id,
                    transition_count=int(getattr(state, "transition_count", 0) or 0) + 1,
                )
                transition = await uow.lifecycle_transitions.create(
                    user_id=user_id,
                    from_stage=previous_stage,
                    to_stage=stage,
                    reasons=normalized_reasons,
                    source=source,
                    reference_id=reference_id,
                    payload=transition_payload,
                    created_at=now,
                )
                changed = True
            else:
                state = await uow.lifecycle_states.update(
                    user_id,
                    current_reasons=normalized_reasons,
                    last_transition_source=source,
                    last_transition_reference_id=reference_id,
                )

            if changed and transition is not None and hasattr(uow, "decision_traces"):
                await uow.decision_traces.create(
                    user_id=user_id,
                    trace_type="lifecycle_transition",
                    source=source,
                    reference_id=reference_id,
                    policy_version="v1",
                    inputs={
                        "from_stage": getattr(transition, "from_stage", None),
                        "to_stage": getattr(transition, "to_stage", stage),
                        "reasons": list(normalized_reasons),
                        "payload": dict(transition_payload),
                    },
                    outputs={
                        "current_stage": str(getattr(state, "current_stage", stage) or stage),
                        "previous_stage": getattr(state, "previous_stage", None),
                        "transition_count": int(getattr(state, "transition_count", 0) or 0),
                        "transition_id": getattr(transition, "id", None),
                    },
                    reason=normalized_reasons[0] if normalized_reasons else None,
                )

            await uow.commit()

        return LifecycleStateWriteResult(
            state=state,
            changed=changed,
            transition=transition,
        )
