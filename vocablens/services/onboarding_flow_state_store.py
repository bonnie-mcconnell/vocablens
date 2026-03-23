from __future__ import annotations

from dataclasses import asdict

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.report_models import (
    OnboardingFlowState,
    OnboardingHabitLockInState,
    OnboardingIdentityState,
    OnboardingPaywallState,
    OnboardingPersonalizationState,
    OnboardingProgressIllusionState,
    OnboardingScheduledNotificationState,
    OnboardingWowPayload,
)


class OnboardingFlowStateStore:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def load(self, user_id: int) -> OnboardingFlowState | None:
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
                return self._deserialize_state(payload["state"])
        return None

    async def save(self, user_id: int, state: OnboardingFlowState, *, event_type: str) -> None:
        snapshot = asdict(state)
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

    def _deserialize_state(self, payload: dict) -> OnboardingFlowState:
        habit_lock_in = payload.get("habit_lock_in", {}) or {}
        scheduled_notification = habit_lock_in.get("scheduled_notification")
        return OnboardingFlowState(
            current_step=payload.get("current_step", "identity_selection"),
            steps_completed=list(payload.get("steps_completed", [])),
            identity=OnboardingIdentityState(**(payload.get("identity", {}) or {})),
            personalization=OnboardingPersonalizationState(**(payload.get("personalization", {}) or {})),
            wow=OnboardingWowPayload(
                score=float((payload.get("wow", {}) or {}).get("score", 0.0) or 0.0),
                qualifies=bool((payload.get("wow", {}) or {}).get("qualifies", False)),
                triggered=bool((payload.get("wow", {}) or {}).get("triggered", False)),
                understood_percent=float((payload.get("wow", {}) or {}).get("understood_percent", 0.0) or 0.0),
                triggers=dict((payload.get("wow", {}) or {}).get("triggers", {}) or {}),
                session_snapshot=dict((payload.get("wow", {}) or {}).get("session_snapshot", {}) or {}),
            ),
            early_success_score=float(payload.get("early_success_score", 0.0) or 0.0),
            progress_illusion=OnboardingProgressIllusionState(**(payload.get("progress_illusion", {}) or {})),
            paywall=OnboardingPaywallState(**(payload.get("paywall", {}) or {})),
            habit_lock_in=OnboardingHabitLockInState(
                preferred_time_of_day=habit_lock_in.get("preferred_time_of_day"),
                preferred_channel=habit_lock_in.get("preferred_channel"),
                frequency_limit=habit_lock_in.get("frequency_limit"),
                scheduled_notification=OnboardingScheduledNotificationState(**scheduled_notification)
                if isinstance(scheduled_notification, dict) and scheduled_notification
                else None,
                ritual=dict(habit_lock_in.get("ritual", {}) or {}),
                pressure=dict(habit_lock_in.get("pressure", {}) or {}),
            ),
        )
