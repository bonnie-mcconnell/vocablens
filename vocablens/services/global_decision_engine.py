from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.lifecycle_stage_policy import LifecycleSnapshot, classify_lifecycle_stage
from vocablens.services.paywall_service import PaywallService
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.user_experience_state import UserExperienceState

PrimaryAction = Literal["learn", "review", "conversation", "upsell", "nudge"]
SessionType = Literal["quick", "deep", "passive"]
MonetizationAction = Literal["none", "soft_paywall", "hard_paywall", "trial_offer"]
EngagementAction = Literal["streak_push", "reward_boost", "habit_nudge"]
LifecycleStage = Literal["new_user", "activating", "engaged", "at_risk", "churned"]


@dataclass(frozen=True)
class GlobalDecision:
    primary_action: PrimaryAction
    difficulty_level: str
    session_type: SessionType
    monetization_action: MonetizationAction
    engagement_action: EngagementAction
    lifecycle_stage: LifecycleStage
    reason: str


class GlobalDecisionEngine:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        retention_engine: RetentionEngine,
        progress_service: ProgressService,
        subscription_service: SubscriptionService,
        paywall_service: PaywallService,
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine
        self._progress = progress_service
        self._subscriptions = subscription_service
        self._paywall = paywall_service

    async def decide(self, user_id: int) -> GlobalDecision:
        retention = await self._retention.assess_user(user_id)
        progress = await self._progress.build_dashboard(user_id)
        features = await self._subscriptions.get_features(user_id)
        paywall = await self._paywall.evaluate(user_id)
        learning_state, engagement_state = await self._state_snapshot(user_id)

        stage, _ = classify_lifecycle_stage(
            snapshot=LifecycleSnapshot(
                learning_state=learning_state,
                engagement_state=engagement_state,
                retention=retention,
            )
        )
        difficulty = self._difficulty(stage, progress, features)
        monetization = self._monetization_action(stage, paywall)
        engagement = self._engagement_action(stage, retention, progress)
        primary, session_type, reason = self._primary_action(
            stage=stage,
            progress=progress,
            paywall=paywall,
            monetization=monetization,
            engagement=engagement,
        )
        return GlobalDecision(
            primary_action=primary,
            difficulty_level=difficulty,
            session_type=session_type,
            monetization_action=monetization,
            engagement_action=engagement,
            lifecycle_stage=stage,
            reason=reason,
        )

    async def user_experience_state(self, user_id: int) -> UserExperienceState:
        retention = await self._retention.assess_user(user_id)
        progress = await self._progress.build_dashboard(user_id)
        features = await self._subscriptions.get_features(user_id)
        paywall = await self._paywall.evaluate(user_id)
        learning_state, engagement_state = await self._state_snapshot(user_id)

        stage, _ = classify_lifecycle_stage(
            snapshot=LifecycleSnapshot(
                learning_state=learning_state,
                engagement_state=engagement_state,
                retention=retention,
            )
        )
        return self._build_user_experience_state(
            stage=stage,
            retention=retention,
            progress=progress,
            features=features,
            paywall=paywall,
            learning_state=learning_state,
            engagement_state=engagement_state,
        )

    async def _state_snapshot(self, user_id: int) -> tuple[object, object]:
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            await uow.commit()
        return learning_state, engagement_state

    def _build_user_experience_state(
        self,
        *,
        stage: LifecycleStage,
        retention,
        progress: dict,
        features,
        paywall,
        learning_state,
        engagement_state,
    ) -> UserExperienceState:
        return UserExperienceState(
            lifecycle_stage=stage,
            retention_state=str(getattr(retention, "state", "unknown")),
            drop_off_risk=round(float(getattr(retention, "drop_off_risk", 0.0) or 0.0), 3),
            total_sessions=int(getattr(engagement_state, "total_sessions", 0) or 0),
            momentum_score=round(float(getattr(engagement_state, "momentum_score", 0.0) or 0.0), 3),
            mastery_percent=round(float(getattr(learning_state, "mastery_percent", 0.0) or 0.0), 2),
            due_reviews=int(progress.get("due_reviews", 0) or 0),
            subscription_tier=str(getattr(features, "tier", "free") or "free"),
            paywall_visible=bool(getattr(paywall, "show_paywall", False)),
            paywall_type=getattr(paywall, "paywall_type", None),
            paywall_allow_access=bool(getattr(paywall, "allow_access", True)),
        )

    def _difficulty(self, stage: LifecycleStage, progress: dict, features) -> str:
        accuracy = float(progress["metrics"].get("accuracy_rate", 0.0))
        fluency = float(progress["metrics"].get("fluency_score", 0.0))
        if stage in {"churned", "at_risk", "new_user"}:
            return "easy"
        if stage == "engaged" and accuracy >= 85 and fluency >= 75 and features.personalization_level != "basic":
            return "hard"
        return "medium"

    def _monetization_action(self, stage: LifecycleStage, paywall) -> MonetizationAction:
        if getattr(paywall, "paywall_type", None) == "hard_paywall":
            return "hard_paywall"
        if getattr(paywall, "trial_recommended", False):
            return "trial_offer"
        if stage == "engaged" and getattr(paywall, "show_paywall", False):
            return "soft_paywall"
        if stage == "engaged" and getattr(paywall, "upsell_recommended", False):
            return "soft_paywall"
        return "none"

    def _engagement_action(self, stage: LifecycleStage, retention, progress: dict) -> EngagementAction:
        daily = progress.get("daily", {})
        if stage == "new_user":
            return "habit_nudge"
        if retention.current_streak >= 2:
            return "streak_push"
        if stage == "engaged" or int(daily.get("words_learned", 0) or 0) > 0:
            return "reward_boost"
        return "habit_nudge"

    def _primary_action(
        self,
        *,
        stage: LifecycleStage,
        progress: dict,
        paywall,
        monetization: MonetizationAction,
        engagement: EngagementAction,
    ) -> tuple[PrimaryAction, SessionType, str]:
        due_reviews = int(progress.get("due_reviews", 0) or 0)
        accuracy = float(progress["metrics"].get("accuracy_rate", 0.0))

        if stage == "churned":
            return "nudge", "passive", "User is churned; reactivation takes priority."
        if stage == "at_risk":
            if due_reviews > 0:
                return "review", "quick", "User is at risk; low-friction review comes first."
            return "conversation", "quick", "User is at risk; short guided conversation is the safest re-entry."
        if stage == "new_user":
            return "conversation", "quick", "New users need activation and a fast wow moment."
        if stage == "activating":
            if accuracy < 70:
                return "review", "quick", "Activation is the priority; review stabilizes early success."
            return "conversation", "quick", "Activation is the priority; guided conversation builds momentum."
        if monetization in {"soft_paywall", "hard_paywall", "trial_offer"}:
            return "upsell", "deep" if monetization != "hard_paywall" else "passive", "Engaged users should see monetization next."
        return "learn", "deep", f"User is engaged; lean into progress with {engagement}."
