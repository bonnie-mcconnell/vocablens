from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import OnboardingFlowStateORM
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


def _map_row(row: OnboardingFlowStateORM) -> OnboardingFlowState:
    habit_lock_in = dict(row.habit_lock_in or {})
    scheduled_notification = habit_lock_in.get("scheduled_notification")
    return OnboardingFlowState(
        current_step=row.current_step,
        steps_completed=list(row.steps_completed or []),
        identity=OnboardingIdentityState(**dict(row.identity or {})),
        personalization=OnboardingPersonalizationState(**dict(row.personalization or {})),
        wow=OnboardingWowPayload(
            score=float(dict(row.wow or {}).get("score", 0.0) or 0.0),
            qualifies=bool(dict(row.wow or {}).get("qualifies", False)),
            triggered=bool(dict(row.wow or {}).get("triggered", False)),
            understood_percent=float(dict(row.wow or {}).get("understood_percent", 0.0) or 0.0),
            triggers=dict(dict(row.wow or {}).get("triggers", {}) or {}),
            session_snapshot=dict(dict(row.wow or {}).get("session_snapshot", {}) or {}),
        ),
        early_success_score=float(row.early_success_score or 0.0),
        progress_illusion=OnboardingProgressIllusionState(**dict(row.progress_illusion or {})),
        paywall=OnboardingPaywallState(**dict(row.paywall or {})),
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


class PostgresOnboardingFlowStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> OnboardingFlowState | None:
        result = await self.session.execute(
            select(OnboardingFlowStateORM).where(OnboardingFlowStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _map_row(row)

    async def upsert(self, user_id: int, state: OnboardingFlowState) -> OnboardingFlowState:
        now = utc_now()
        values = {
            "user_id": user_id,
            "current_step": state.current_step,
            "steps_completed": list(state.steps_completed),
            "identity": asdict(state.identity),
            "personalization": asdict(state.personalization),
            "wow": asdict(state.wow),
            "early_success_score": float(state.early_success_score),
            "progress_illusion": asdict(state.progress_illusion),
            "paywall": asdict(state.paywall),
            "habit_lock_in": asdict(state.habit_lock_in),
            "updated_at": now,
        }

        existing = await self.get(user_id)
        if existing is None:
            await self.session.execute(
                insert(OnboardingFlowStateORM).values(
                    created_at=now,
                    **values,
                )
            )
        else:
            await self.session.execute(
                update(OnboardingFlowStateORM)
                .where(OnboardingFlowStateORM.user_id == user_id)
                .values(**values)
            )
        await self.session.flush()
        refreshed = await self.get(user_id)
        if refreshed is None:
            raise RuntimeError("Failed to persist onboarding flow state")
        return refreshed
