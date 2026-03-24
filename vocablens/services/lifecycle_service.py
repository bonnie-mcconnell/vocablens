from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.lifecycle_stage_policy import LifecycleSnapshot, classify_lifecycle_stage
from vocablens.services.lifecycle_state_service import LifecycleStateService
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.notification_state_service import NotificationStateService
from vocablens.services.onboarding_service import OnboardingService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.progress_service import ProgressService
from vocablens.services.report_models import (
    LifecycleAction,
    LifecycleNotification,
    LifecyclePaywallState,
)
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine

LifecycleStage = Literal["new_user", "activating", "engaged", "at_risk", "churned"]


@dataclass(frozen=True)
class LifecyclePlan:
    stage: LifecycleStage
    reasons: list[str]
    actions: list[LifecycleAction]
    paywall: LifecyclePaywallState
    notification: LifecycleNotification


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
        lifecycle_state_service: LifecycleStateService | None = None,
        notification_state_service: NotificationStateService | None = None,
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine
        self._progress = progress_service
        self._notifications = notification_engine
        self._paywall = paywall_service
        self._global_decision = global_decision_engine
        self._onboarding = onboarding_service
        self._lifecycle_states = lifecycle_state_service or LifecycleStateService(uow_factory)
        self._notification_states = notification_state_service or NotificationStateService(uow_factory)

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
        await self._record_action_trace(
            user_id=user_id,
            stage=stage,
            reasons=reasons,
            actions=actions,
            source="lifecycle_service.evaluate",
        )
        await self._record_canonical_state(
            user_id=user_id,
            stage=stage,
            reasons=reasons,
            retention=retention,
            learning_state=learning_state,
            engagement_state=engagement_state,
            source="lifecycle_service.evaluate",
        )
        await self._notification_states.apply_lifecycle_policy(
            user_id=user_id,
            lifecycle_stage=stage,
            source="lifecycle_service.evaluate",
            reference_id=f"lifecycle:{user_id}",
        )
        notification = await self._notification_for_stage(stage, user_id, retention, actions)

        plan = LifecyclePlan(
            stage=stage,
            reasons=reasons,
            actions=actions,
            paywall=LifecyclePaywallState(
                show=paywall.show_paywall,
                type=paywall.paywall_type,
                reason=paywall.reason,
                usage_percent=paywall.usage_percent,
                allow_access=paywall.allow_access,
            ),
            notification=notification,
        )
        await self._record_decision_trace(
            user_id=user_id,
            plan=plan,
            retention=retention,
            learning_state=learning_state,
            engagement_state=engagement_state,
            paywall=paywall,
            source="lifecycle_service.evaluate",
        )
        return plan

    async def _state_snapshot(self, user_id: int):
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            await uow.commit()
        return learning_state, engagement_state

    def _actions_for_stage(self, stage: LifecycleStage, retention: RetentionAssessment, paywall, learning_state, engagement_state) -> list[LifecycleAction]:
        actions: list[LifecycleAction] = []
        weak_area = next(iter(getattr(learning_state, "weak_areas", []) or []), "core skills")
        mastery = float(getattr(learning_state, "mastery_percent", 0.0) or 0.0)
        if stage == "new_user":
            actions.append(LifecycleAction(type="onboarding_nudge", message="Guide the user to complete the first meaningful session."))
            actions.append(LifecycleAction(type="quick_start_path", message="Surface the easiest next lesson and tutor mode entry point."))
        elif stage == "activating":
            actions.append(LifecycleAction(type="wow_moment_push", message=f"Guide the user toward a clean success around {weak_area}."))
            actions.append(LifecycleAction(type="progress_visibility", message=f"Highlight current mastery at {mastery}%."))
        elif stage == "engaged":
            actions.append(LifecycleAction(type="monetization_prompt", message="Show the paid value clearly without interrupting a productive stretch."))
            if paywall.show_paywall:
                actions.append(LifecycleAction(type="paywall_follow_up", message=f"Paywall available: {paywall.paywall_type} for {paywall.reason}."))
        elif stage == "at_risk":
            actions.append(LifecycleAction(type="reengagement_flow", message="Run a low-friction comeback flow."))
            for action in retention.suggested_actions[:2]:
                actions.append(LifecycleAction(type=action.kind, message=action.reason, target=action.target))
        elif stage == "churned":
            actions.append(LifecycleAction(type="win_back_flow", message="Offer a straightforward restart path with a reminder of what is worth returning for."))
        return actions

    async def _notification_for_stage(
        self,
        stage: LifecycleStage,
        user_id: int,
        retention: RetentionAssessment,
        actions: list[LifecycleAction],
    ) -> LifecycleNotification:
        if stage not in {"at_risk", "churned", "new_user", "activating"}:
            return LifecycleNotification(should_send=False, reason="stage does not require proactive lifecycle messaging")
        decision = await self._notifications.decide(
            user_id,
            retention,
            reference_id=f"lifecycle:{user_id}",
            source_context="lifecycle_service.notification",
        )
        return LifecycleNotification(
            should_send=decision.should_send,
            reason=decision.reason,
            channel=decision.channel,
            send_at=decision.send_at.isoformat() if getattr(decision.send_at, "isoformat", None) else None,
            category=decision.message.category if decision.message else (actions[0].type if actions else None),
        )

    async def _evaluate_from_global_decision(self, user_id: int) -> LifecyclePlan:
        decision = await self._global_decision.decide(user_id)
        retention = await self._retention.assess_user(user_id)
        learning_state, engagement_state = await self._state_snapshot(user_id)
        paywall = await self._paywall.evaluate(user_id)
        stage = decision.lifecycle_stage
        reasons = [decision.reason]
        actions = self._actions_for_stage(stage, retention, paywall, learning_state, engagement_state)
        actions.extend(await self._onboarding_actions(user_id, stage))
        await self._record_action_trace(
            user_id=user_id,
            stage=stage,
            reasons=reasons,
            actions=actions,
            source="lifecycle_service.global_decision",
        )
        await self._record_canonical_state(
            user_id=user_id,
            stage=stage,
            reasons=reasons,
            retention=retention,
            learning_state=learning_state,
            engagement_state=engagement_state,
            source="lifecycle_service.global_decision",
        )
        await self._notification_states.apply_lifecycle_policy(
            user_id=user_id,
            lifecycle_stage=stage,
            source="lifecycle_service.global_decision",
            reference_id=f"lifecycle:{user_id}",
        )
        notification = await self._notification_for_stage(stage, user_id, retention, actions)
        plan = LifecyclePlan(
            stage=stage,
            reasons=reasons,
            actions=actions,
            paywall=LifecyclePaywallState(
                show=paywall.show_paywall,
                type=paywall.paywall_type,
                reason=paywall.reason,
                usage_percent=paywall.usage_percent,
                allow_access=paywall.allow_access,
            ),
            notification=notification,
        )
        await self._record_decision_trace(
            user_id=user_id,
            plan=plan,
            retention=retention,
            learning_state=learning_state,
            engagement_state=engagement_state,
            paywall=paywall,
            source="lifecycle_service.global_decision",
            global_reason=decision.reason,
        )
        return plan

    async def _onboarding_actions(self, user_id: int, stage: LifecycleStage) -> list[LifecycleAction]:
        if not self._onboarding or stage not in {"new_user", "activating"}:
            return []
        plan = await self._onboarding.plan(user_id)
        return [
            LifecycleAction(type="goal_capture", message=step.message)
            if step.type == "goal_capture"
            else LifecycleAction(type=step.type, message=step.message)
            for step in plan.guided_flow
        ]

    async def _record_decision_trace(
        self,
        *,
        user_id: int,
        plan: LifecyclePlan,
        retention: RetentionAssessment,
        learning_state,
        engagement_state,
        paywall,
        source: str,
        global_reason: str | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="lifecycle_decision",
                source=source,
                reference_id=f"lifecycle:{user_id}",
                policy_version="v1",
                inputs={
                    "retention": {
                        "state": retention.state,
                        "drop_off_risk": round(float(retention.drop_off_risk or 0.0), 3),
                        "session_frequency": round(float(retention.session_frequency or 0.0), 3),
                        "current_streak": int(retention.current_streak or 0),
                        "is_high_engagement": bool(retention.is_high_engagement),
                        "suggested_action_types": [action.kind for action in retention.suggested_actions],
                    },
                    "learning_state": {
                        "weak_areas": list(getattr(learning_state, "weak_areas", []) or []),
                        "mastery_percent": round(float(getattr(learning_state, "mastery_percent", 0.0) or 0.0), 2),
                        "skills": dict(getattr(learning_state, "skills", {}) or {}),
                    },
                    "engagement_state": {
                        "total_sessions": int(getattr(engagement_state, "total_sessions", 0) or 0),
                        "momentum_score": round(float(getattr(engagement_state, "momentum_score", 0.0) or 0.0), 3),
                        "sessions_last_3_days": int(getattr(engagement_state, "sessions_last_3_days", 0) or 0),
                    },
                    "paywall": {
                        "show_paywall": bool(getattr(paywall, "show_paywall", False)),
                        "paywall_type": getattr(paywall, "paywall_type", None),
                        "reason": getattr(paywall, "reason", None),
                        "usage_percent": int(getattr(paywall, "usage_percent", 0) or 0),
                        "allow_access": bool(getattr(paywall, "allow_access", True)),
                    },
                    "global_reason": global_reason,
                },
                outputs={
                    "stage": plan.stage,
                    "reasons": list(plan.reasons),
                    "action_types": [action.type for action in plan.actions],
                    "actions": [asdict(action) for action in plan.actions],
                    "paywall": asdict(plan.paywall),
                    "notification": asdict(plan.notification),
                },
                reason=plan.reasons[0] if plan.reasons else global_reason,
            )
            await uow.commit()

    async def _record_canonical_state(
        self,
        *,
        user_id: int,
        stage: LifecycleStage,
        reasons: list[str],
        retention: RetentionAssessment,
        learning_state,
        engagement_state,
        source: str,
    ) -> None:
        await self._lifecycle_states.record_stage(
            user_id=user_id,
            stage=stage,
            reasons=reasons,
            source=source,
            reference_id=f"lifecycle:{user_id}",
            payload={
                "retention_state": retention.state,
                "drop_off_risk": round(float(retention.drop_off_risk or 0.0), 3),
                "total_sessions": int(getattr(engagement_state, "total_sessions", 0) or 0),
                "sessions_last_3_days": int(getattr(engagement_state, "sessions_last_3_days", 0) or 0),
                "mastery_percent": round(float(getattr(learning_state, "mastery_percent", 0.0) or 0.0), 2),
                "weak_areas": list(getattr(learning_state, "weak_areas", []) or []),
            },
        )

    async def _record_action_trace(
        self,
        *,
        user_id: int,
        stage: LifecycleStage,
        reasons: list[str],
        actions: list[LifecycleAction],
        source: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="lifecycle_action_plan",
                source=source,
                reference_id=f"lifecycle:{user_id}",
                policy_version="v1",
                inputs={
                    "stage": stage,
                    "reasons": list(reasons),
                },
                outputs={
                    "action_types": [action.type for action in actions],
                    "actions": [asdict(action) for action in actions],
                },
                reason=reasons[0] if reasons else f"Lifecycle stage {stage} generated action plan.",
            )
            await uow.commit()
