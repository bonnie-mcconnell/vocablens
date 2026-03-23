from __future__ import annotations

from dataclasses import dataclass

from vocablens.services.engagement_loop_policy import EngagementLoopContext, EngagementLoopPolicy
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.progress_service import ProgressService
from vocablens.services.report_models import HabitAction, HabitRepeat, HabitReward, HabitTrigger
from vocablens.services.retention_engine import RetentionEngine


@dataclass(frozen=True)
class HabitLoopPlan:
    trigger: HabitTrigger
    action: HabitAction
    reward: HabitReward
    repeat: HabitRepeat


class HabitEngine:
    def __init__(
        self,
        retention_engine: RetentionEngine,
        notification_engine: NotificationDecisionEngine,
        progress_service: ProgressService,
        global_decision_engine: GlobalDecisionEngine | None = None,
    ):
        self._retention = retention_engine
        self._notifications = notification_engine
        self._progress = progress_service
        self._global_decision = global_decision_engine
        self._policy = EngagementLoopPolicy()

    async def execute(self, user_id: int) -> HabitLoopPlan:
        if self._global_decision:
            return await self._execute_from_global_decision(user_id)
        context = await self._load_context(user_id)
        trigger = self._policy.build_trigger(context.retention, context.notification)
        action = self._policy.build_action(context.retention, context.progress)
        reward = self._policy.build_reward(context.retention, context.progress, action)
        repeat = self._policy.build_repeat(context.retention, trigger, reward)

        return HabitLoopPlan(
            trigger=trigger,
            action=action,
            reward=reward,
            repeat=repeat,
        )

    async def _load_context(self, user_id: int) -> EngagementLoopContext:
        retention = await self._retention.assess_user(user_id)
        progress = await self._progress.build_dashboard(user_id)
        notification = await self._notifications.decide(user_id, retention)
        return EngagementLoopContext(
            retention=retention,
            progress=progress,
            notification=notification,
        )

    async def _execute_from_global_decision(self, user_id: int) -> HabitLoopPlan:
        decision = await self._global_decision.decide(user_id)
        context = await self._load_context(user_id)
        trigger = self._policy.build_trigger(context.retention, context.notification)
        action = HabitAction(
            type="quick_session",
            duration_minutes=3 if decision.session_type == "quick" else 2 if decision.session_type == "passive" else 5,
            target=decision.primary_action if decision.primary_action in {"learn", "review", "conversation"} else "review",
            reason=decision.reason,
        )
        reward = self._policy.build_reward(context.retention, context.progress, action)
        repeat = HabitRepeat(
            should_repeat=decision.lifecycle_stage in {"new_user", "activating", "at_risk", "engaged"},
            next_best_trigger="streak_reminder" if decision.engagement_action == "streak_push" else "notification",
            cadence="daily",
        )
        return HabitLoopPlan(trigger=trigger, action=action, reward=reward, repeat=repeat)
