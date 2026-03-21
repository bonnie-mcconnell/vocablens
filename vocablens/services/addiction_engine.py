from __future__ import annotations

from dataclasses import dataclass

from vocablens.services.engagement_loop_policy import EngagementLoopPolicy
from vocablens.services.habit_engine import HabitEngine
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine


@dataclass(frozen=True)
class AddictionLoopPlan:
    trigger: dict
    action: dict
    reward: dict
    pressure: dict
    identity: dict
    ritual: dict


class AddictionEngine:
    def __init__(
        self,
        habit_engine: HabitEngine,
        retention_engine: RetentionEngine,
        notification_engine: NotificationDecisionEngine,
        progress_service: ProgressService,
    ):
        self._habit = habit_engine
        self._retention = retention_engine
        self._notifications = notification_engine
        self._progress = progress_service
        self._policy = EngagementLoopPolicy()

    async def execute(self, user_id: int) -> AddictionLoopPlan:
        habit = await self._habit.execute(user_id)
        retention = await self._retention.assess_user(user_id)
        progress = await self._progress.build_dashboard(user_id)
        notification = await self._notifications.decide(user_id, retention)

        reward = self._policy.build_variable_reward(user_id=user_id, retention=retention, reward=habit.reward)
        pressure = self._policy.build_loss_aversion(retention, progress)
        identity = self._policy.build_identity_reinforcement(progress)
        ritual = self._policy.build_ritual_hook(notification, retention)

        return AddictionLoopPlan(
            trigger=habit.trigger,
            action=habit.action,
            reward=reward,
            pressure=pressure,
            identity=identity,
            ritual=ritual,
        )
