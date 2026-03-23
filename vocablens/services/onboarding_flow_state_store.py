from __future__ import annotations

from dataclasses import asdict

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.report_models import OnboardingFlowState, OnboardingWowPayload


class OnboardingFlowStateStore:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def load(self, user_id: int) -> OnboardingFlowState | None:
        async with self._uow_factory() as uow:
            state = await uow.onboarding_states.get(user_id)
            await uow.commit()
        return state

    async def save(self, user_id: int, state: OnboardingFlowState, *, event_type: str) -> None:
        snapshot = asdict(state)
        async with self._uow_factory() as uow:
            await uow.onboarding_states.upsert(user_id, state)
            await uow.events.record(
                user_id=user_id,
                event_type=event_type,
                payload={
                    "current_step": snapshot["current_step"],
                    "steps_completed_count": len(snapshot["steps_completed"]),
                    "updated_at": utc_now().isoformat(),
                },
            )
            await uow.commit()

    def default_state(self) -> OnboardingFlowState:
        return OnboardingFlowState(
            current_step="identity_selection",
            wow=OnboardingWowPayload(
                score=0.0,
                qualifies=False,
                triggered=False,
                understood_percent=0.0,
            ),
        )
