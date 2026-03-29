from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from vocablens.services.engagement_loop_policy import EngagementLoopPolicy
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.habit_engine import HabitEngine
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.progress_service import ProgressService
from vocablens.services.report_models import (
    HabitAction,
    HabitTrigger,
    IdentityReinforcement,
    LossAversionPlan,
    RitualHook,
    VariableReward,
)
from vocablens.services.retention_engine import RetentionEngine


@dataclass(frozen=True)
class AddictionLoopPlan:
    trigger: HabitTrigger
    action: HabitAction
    reward: VariableReward
    pressure: LossAversionPlan
    identity: IdentityReinforcement
    ritual: RitualHook


class AddictionEngine:
    def __init__(
        self,
        habit_engine: HabitEngine,
        retention_engine: RetentionEngine,
        notification_engine: NotificationDecisionEngine,
        progress_service: ProgressService,
        global_decision_engine: GlobalDecisionEngine | None = None,
    ):
        self._habit = habit_engine
        self._retention = retention_engine
        self._notifications = notification_engine
        self._progress = progress_service
        self._global_decision = global_decision_engine
        self._policy = EngagementLoopPolicy()

    async def execute(self, user_id: int) -> AddictionLoopPlan:
        habit = await self._habit.execute(user_id)
        retention = await self._retention.assess_user(user_id)
        retention = await self._retention_from_canonical_state(user_id, retention)
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

    async def _retention_from_canonical_state(self, user_id: int, retention):
        if self._global_decision is None or not hasattr(self._global_decision, "user_experience_state"):
            return retention
        user_state = await self._global_decision.user_experience_state(user_id)
        if user_state is None:
            return retention
        retention_state = getattr(user_state, "retention_state", None)
        normalized_state = retention_state.replace("_", "-") if isinstance(retention_state, str) else retention.state
        payload = dict(vars(retention))
        payload["state"] = normalized_state
        payload["drop_off_risk"] = float(
            getattr(user_state, "drop_off_risk", getattr(retention, "drop_off_risk", 0.0)) or 0.0
        )
        return SimpleNamespace(**payload)
