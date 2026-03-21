from __future__ import annotations

from copy import deepcopy

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


class OnboardingFlowStateStore:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def load(self, user_id: int) -> dict | None:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=200)
            await uow.commit()
        for event in events:
            if getattr(event, "event_type", None) not in {
                "onboarding_state_updated",
                "onboarding_started",
                "onboarding_completed",
            }:
                continue
            payload = getattr(event, "payload", None)
            if isinstance(payload, dict) and payload.get("state"):
                return dict(payload["state"])
        return None

    async def save(self, user_id: int, state: dict, *, event_type: str) -> None:
        snapshot = deepcopy(state)
        async with self._uow_factory() as uow:
            await uow.events.record(
                user_id=user_id,
                event_type=event_type,
                payload={
                    "state": snapshot,
                    "current_step": snapshot["current_step"],
                    "updated_at": utc_now().isoformat(),
                },
            )
            await uow.commit()

    def default_state(self) -> dict:
        return {
            "current_step": "identity_selection",
            "steps_completed": [],
            "identity": {},
            "personalization": {},
            "wow": {"score": 0.0, "qualifies": False, "understood_percent": 0.0, "triggers": {}},
            "early_success_score": 0.0,
            "progress_illusion": {},
            "paywall": {"show": False},
            "habit_lock_in": {},
        }
