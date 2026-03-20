from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.global_decision_engine import GlobalDecisionEngine
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
        progress = await self._progress.build_dashboard(user_id)
        retention = await self._retention.assess_user(user_id)
        paywall = await self._paywall.evaluate(user_id)
        sessions = await self._session_count(user_id)

        stage, reasons = self._classify(
            sessions=sessions,
            retention=retention,
            progress=progress,
        )
        actions = self._actions_for_stage(stage, retention, paywall, progress)
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

    async def _session_count(self, user_id: int) -> int:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=500)
            await uow.commit()
        return sum(1 for event in events if getattr(event, "event_type", None) == "session_started")

    def _classify(self, *, sessions: int, retention: RetentionAssessment, progress: dict) -> tuple[LifecycleStage, list[str]]:
        reasons: list[str] = []
        if retention.state == "churned":
            reasons.append("retention engine marked user as churned")
            return "churned", reasons
        if retention.state == "at-risk":
            reasons.append("retention engine marked user as at risk")
            return "at_risk", reasons
        if sessions <= 1:
            reasons.append("user has one or fewer sessions")
            return "new_user", reasons

        accuracy = float(progress["metrics"].get("accuracy_rate", 0.0))
        mastery = float(progress["metrics"].get("vocabulary_mastery_percent", 0.0))
        fluency = float(progress["metrics"].get("fluency_score", 0.0))

        if sessions < 5 or accuracy < 70 or fluency < 60:
            reasons.append("user is building toward activation")
            return "activating", reasons

        if retention.is_high_engagement or (sessions >= 5 and mastery >= 40 and accuracy >= 75 and fluency >= 65):
            reasons.append("user shows strong engagement and progress")
            return "engaged", reasons

        reasons.append("defaulted to activating based on moderate engagement")
        return "activating", reasons

    def _actions_for_stage(self, stage: LifecycleStage, retention: RetentionAssessment, paywall, progress: dict) -> list[dict]:
        actions: list[dict] = []
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
                    "message": "Drive the user to a successful tutor interaction quickly.",
                }
            )
            actions.append(
                {
                    "type": "progress_visibility",
                    "message": f"Highlight current accuracy at {progress['metrics'].get('accuracy_rate', 0.0)}%.",
                }
            )
        elif stage == "engaged":
            actions.append(
                {
                    "type": "monetization_prompt",
                    "message": "Show premium value at the right moment without reducing momentum.",
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
                    "message": "Offer a simple restart path with a strong value reminder.",
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
        progress = await self._progress.build_dashboard(user_id)
        paywall = await self._paywall.evaluate(user_id)
        stage = decision.lifecycle_stage
        reasons = [decision.reason]
        actions = self._actions_for_stage(stage, retention, paywall, progress)
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
