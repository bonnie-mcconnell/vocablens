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
        return MonetizationDecision(
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

    async def _state_snapshot(self, user_id: int):
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            await uow.commit()
        return learning_state, engagement_state, progress_state
