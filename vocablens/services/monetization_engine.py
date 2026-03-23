from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.business_metrics_service import BusinessMetricsService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.monetization_policy import MonetizationPolicy
from vocablens.services.onboarding_flow_service import OnboardingFlowService
from vocablens.services.report_models import (
    MonetizationPricing,
    MonetizationTrigger,
    MonetizationValueDisplay,
)


@dataclass(frozen=True)
class MonetizationDecision:
    show_paywall: bool
    paywall_type: str | None
    offer_type: str
    pricing: MonetizationPricing
    trigger: MonetizationTrigger
    value_display: MonetizationValueDisplay
    strategy: str
    lifecycle_stage: str
    onboarding_step: str | None
    user_segment: str
    trial_days: int | None

    def as_dict(self) -> dict:
        return asdict(self)


class MonetizationEngine:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        paywall_service: AdaptivePaywallService,
        business_metrics_service: BusinessMetricsService,
        onboarding_flow_service: OnboardingFlowService,
        lifecycle_service: LifecycleService,
    ):
        self._uow_factory = uow_factory
        self._paywall = paywall_service
        self._business_metrics = business_metrics_service
        self._onboarding_flow = onboarding_flow_service
        self._lifecycle = lifecycle_service
        self._policy = MonetizationPolicy()

    async def evaluate(
        self,
        user_id: int,
        *,
        geography: str | None = None,
        wow_score: float | None = None,
    ) -> MonetizationDecision:
        paywall = await self._paywall.evaluate(user_id, wow_score=wow_score)
        lifecycle = await self._lifecycle.evaluate(user_id)
        onboarding_state = await self._onboarding_flow.current_state(user_id)
        business_metrics = await self._business_metrics.dashboard()
        if is_dataclass(business_metrics):
            business_metrics = asdict(business_metrics)
        learning_state, engagement_state, progress_state = await self._state_snapshot(user_id)

        onboarding_step = onboarding_state.get("current_step") if onboarding_state else None
        geography_code = self._policy.normalize_geography(geography)
        pricing = self._policy.build_pricing(
            paywall=paywall,
            lifecycle=lifecycle,
            onboarding_state=onboarding_state,
            engagement_state=engagement_state,
            business_metrics=business_metrics,
            geography=geography_code,
        )
        offer_type = self._policy.offer_type(paywall=paywall, lifecycle=lifecycle, onboarding_state=onboarding_state)
        show_paywall = self._policy.should_show_paywall(
            paywall=paywall,
            lifecycle=lifecycle,
            onboarding_step=onboarding_step,
        )
        if not show_paywall and offer_type == "annual_anchor":
            offer_type = "none"

        strategy = self._policy.strategy(paywall=paywall, offer_type=offer_type, geography=geography_code)
        decision = MonetizationDecision(
            show_paywall=show_paywall,
            paywall_type=paywall.paywall_type if show_paywall else None,
            offer_type=offer_type,
            pricing=pricing,
            trigger=self._policy.trigger_payload(
                paywall=paywall,
                lifecycle=lifecycle,
                onboarding_step=onboarding_step,
                show_paywall=show_paywall,
            ),
            value_display=self._policy.value_display(
                paywall=paywall,
                lifecycle=lifecycle,
                onboarding_state=onboarding_state,
                learning_state=learning_state,
                progress_state=progress_state,
                offer_type=offer_type,
            ),
            strategy=strategy,
            lifecycle_stage=lifecycle.stage,
            onboarding_step=onboarding_step,
            user_segment=paywall.user_segment,
            trial_days=paywall.trial_days if offer_type == "trial" else None,
        )
        await self._record_decision_trace(
            user_id=user_id,
            geography=geography_code,
            wow_score=wow_score,
            paywall=paywall,
            lifecycle=lifecycle,
            onboarding_state=onboarding_state,
            learning_state=learning_state,
            engagement_state=engagement_state,
            progress_state=progress_state,
            decision=decision,
        )
        return decision

    async def _state_snapshot(self, user_id: int):
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            await uow.commit()
        return learning_state, engagement_state, progress_state

    async def _record_decision_trace(
        self,
        *,
        user_id: int,
        geography: str,
        wow_score: float | None,
        paywall,
        lifecycle,
        onboarding_state: dict | None,
        learning_state,
        engagement_state,
        progress_state,
        decision: MonetizationDecision,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="monetization_decision",
                source="monetization_engine.evaluate",
                reference_id=f"monetization:{user_id}",
                policy_version="v1",
                inputs={
                    "geography": geography,
                    "wow_score": None if wow_score is None else round(float(wow_score), 3),
                    "paywall": {
                        "show_paywall": bool(getattr(paywall, "show_paywall", False)),
                        "paywall_type": getattr(paywall, "paywall_type", None),
                        "reason": getattr(paywall, "reason", None),
                        "usage_percent": int(getattr(paywall, "usage_percent", 0) or 0),
                        "user_segment": getattr(paywall, "user_segment", None),
                        "strategy": getattr(paywall, "strategy", None),
                        "trigger_variant": getattr(paywall, "trigger_variant", None),
                        "pricing_variant": getattr(paywall, "pricing_variant", None),
                        "trial_days": getattr(paywall, "trial_days", None),
                        "trial_recommended": bool(getattr(paywall, "trial_recommended", False)),
                        "trial_active": bool(getattr(paywall, "trial_active", False)),
                    },
                    "lifecycle": {
                        "stage": getattr(lifecycle, "stage", None),
                        "reasons": list(getattr(lifecycle, "reasons", []) or []),
                    },
                    "onboarding_state": {
                        "current_step": onboarding_state.get("current_step") if onboarding_state else None,
                        "paywall": dict(onboarding_state.get("paywall", {}) or {}) if onboarding_state else {},
                        "progress_illusion": dict(onboarding_state.get("progress_illusion", {}) or {}) if onboarding_state else {},
                    },
                    "learning_state": {
                        "mastery_percent": round(float(getattr(learning_state, "mastery_percent", 0.0) or 0.0), 2),
                        "weak_areas": list(getattr(learning_state, "weak_areas", []) or []),
                    },
                    "engagement_state": {
                        "momentum_score": round(float(getattr(engagement_state, "momentum_score", 0.0) or 0.0), 3),
                    },
                    "progress_state": {
                        "xp": int(getattr(progress_state, "xp", 0) or 0),
                        "level": int(getattr(progress_state, "level", 1) or 1),
                    },
                },
                outputs=decision.as_dict(),
                reason=decision.trigger.trigger_reason or decision.strategy,
            )
            await uow.commit()
