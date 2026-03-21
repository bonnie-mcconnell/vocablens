from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.lifecycle_stage_policy import LifecycleSnapshot, classify_lifecycle_stage
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.onboarding_service import OnboardingService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine

LifecycleStage = Literal["new_user", "activating", "engaged", "at_risk", "churned"]


@dataclass(frozen=True)
class LifecyclePlan:
    stage: LifecycleStage
    reasons: list[str]
    actions: list[dict]
    paywall: dict
    notification: dict


class LifecycleService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        retention_engine: RetentionEngine,
        progress_service: ProgressService,
        notification_engine: NotificationDecisionEngine,
        paywall_service: PaywallService,
        global_decision_engine: GlobalDecisionEngine | None = None,
        onboarding_service: OnboardingService | None = None,
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine
        self._progress = progress_service
        self._notifications = notification_engine
        self._paywall = paywall_service
        self._global_decision = global_decision_engine
        self._onboarding = onboarding_service

    async def evaluate(self, user_id: int) -> LifecyclePlan:
        if self._global_decision:
            return await self._evaluate_from_global_decision(user_id)
        retention = await self._retention.assess_user(user_id)
        paywall = await self._paywall.evaluate(user_id)
        learning_state, engagement_state = await self._state_snapshot(user_id)

        stage, reasons = classify_lifecycle_stage(
            snapshot=LifecycleSnapshot(
                learning_state=learning_state,
                engagement_state=engagement_state,
                retention=retention,
            )
        )
        actions = self._actions_for_stage(stage, retention, paywall, learning_state, engagement_state)
        actions.extend(await self._onboarding_actions(user_id, stage))
        notification = await self._notification_for_stage(stage, user_id, retention, actions)

        return LifecyclePlan(
            stage=stage,
            reasons=reasons,
            actions=actions,
            paywall={
                "show": paywall.show_paywall,
                "type": paywall.paywall_type,
                "reason": paywall.reason,
                "usage_percent": paywall.usage_percent,
                "allow_access": paywall.allow_access,
            },
            notification=notification,
        )

    async def _state_snapshot(self, user_id: int):
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            await uow.commit()
        return learning_state, engagement_state

    def _actions_for_stage(self, stage: LifecycleStage, retention: RetentionAssessment, paywall, learning_state, engagement_state) -> list[dict]:
        actions: list[dict] = []
        weak_area = next(iter(getattr(learning_state, "weak_areas", []) or []), "core skills")
        mastery = float(getattr(learning_state, "mastery_percent", 0.0) or 0.0)
        if stage == "new_user":
            actions.append(
                {
                    "type": "onboarding_nudge",
                    "message": "Guide the user to complete the first meaningful session.",
                }
            )
            actions.append(
                {
                    "type": "quick_start_path",
                    "message": "Surface the easiest next lesson and tutor mode entry point.",
                }
            )
        elif stage == "activating":
            actions.append(
                {
                    "type": "wow_moment_push",
                    "message": f"Guide the user toward a clean success around {weak_area}.",
                }
            )
            actions.append(
                {
                    "type": "progress_visibility",
                    "message": f"Highlight current mastery at {mastery}%.",
                }
            )
        elif stage == "engaged":
            actions.append(
                {
                    "type": "monetization_prompt",
                    "message": "Show the paid value clearly without interrupting a productive stretch.",
                }
            )
            if paywall.show_paywall:
                actions.append(
                    {
                        "type": "paywall_follow_up",
                        "message": f"Paywall available: {paywall.paywall_type} for {paywall.reason}.",
                    }
                )
        elif stage == "at_risk":
            actions.append(
                {
                    "type": "reengagement_flow",
                    "message": "Run a low-friction comeback flow.",
                }
            )
            for action in retention.suggested_actions[:2]:
                actions.append(
                    {
                        "type": action.kind,
                        "message": action.reason,
                        "target": action.target,
                    }
                )
        elif stage == "churned":
            actions.append(
                {
                    "type": "win_back_flow",
                    "message": "Offer a straightforward restart path with a reminder of what is worth returning for.",
                }
            )
        return actions

    async def _notification_for_stage(
        self,
        stage: LifecycleStage,
        user_id: int,
        retention: RetentionAssessment,
        actions: list[dict],
    ) -> dict:
        if stage not in {"at_risk", "churned", "new_user", "activating"}:
            return {"should_send": False, "reason": "stage does not require proactive lifecycle messaging"}
        decision = await self._notifications.decide(user_id, retention)
        return {
            "should_send": decision.should_send,
            "reason": decision.reason,
            "channel": decision.channel,
            "send_at": decision.send_at.isoformat() if getattr(decision.send_at, "isoformat", None) else None,
            "category": decision.message.category if decision.message else (actions[0]["type"] if actions else None),
        }

    async def _evaluate_from_global_decision(self, user_id: int) -> LifecyclePlan:
        decision = await self._global_decision.decide(user_id)
        retention = await self._retention.assess_user(user_id)
        learning_state, engagement_state = await self._state_snapshot(user_id)
        paywall = await self._paywall.evaluate(user_id)
        stage = decision.lifecycle_stage
        reasons = [decision.reason]
        actions = self._actions_for_stage(stage, retention, paywall, learning_state, engagement_state)
        actions.extend(await self._onboarding_actions(user_id, stage))
        notification = await self._notification_for_stage(stage, user_id, retention, actions)
        return LifecyclePlan(
            stage=stage,
            reasons=reasons,
            actions=actions,
            paywall={
                "show": paywall.show_paywall,
                "type": paywall.paywall_type,
                "reason": paywall.reason,
                "usage_percent": paywall.usage_percent,
                "allow_access": paywall.allow_access,
            },
            notification=notification,
        )

    async def _onboarding_actions(self, user_id: int, stage: LifecycleStage) -> list[dict]:
        if not self._onboarding or stage not in {"new_user", "activating"}:
            return []
        plan = await self._onboarding.plan(user_id)
        return [
            {"type": "goal_capture", "message": step["message"]}
            if step["type"] == "goal_capture"
            else {"type": step["type"], "message": step["message"]}
            for step in plan.guided_flow
        ]
