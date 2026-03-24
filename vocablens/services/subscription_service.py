from dataclasses import dataclass

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.monetization_state_service import MonetizationStateService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.report_models import ConversionMetrics


@dataclass(frozen=True)
class SubscriptionFeatures:
    tier: str
    request_limit: int
    token_limit: int
    tutor_depth: str
    explanation_quality: str
    personalization_level: str
    paywall_variant: str | None = None
    trial_active: bool = False
    trial_ends_at: object | None = None
    usage_percent: int = 0
    paywall_type: str | None = None
    paywall_reason: str | None = None
    allow_access: bool = True


TIER_FEATURES = {
    "free": SubscriptionFeatures(
        tier="free",
        request_limit=100,
        token_limit=50000,
        tutor_depth="basic",
        explanation_quality="basic",
        personalization_level="basic",
    ),
    "pro": SubscriptionFeatures(
        tier="pro",
        request_limit=1000,
        token_limit=300000,
        tutor_depth="standard",
        explanation_quality="standard",
        personalization_level="standard",
    ),
    "premium": SubscriptionFeatures(
        tier="premium",
        request_limit=10000,
        token_limit=1000000,
        tutor_depth="deep",
        explanation_quality="premium",
        personalization_level="premium",
    ),
}


class SubscriptionService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        experiment_service: ExperimentService | None = None,
        event_service: EventService | None = None,
        paywall_service: PaywallService | None = None,
        monetization_state_service: MonetizationStateService | None = None,
    ):
        self._uow_factory = uow_factory
        self._experiments = experiment_service
        self._event_service = event_service
        self._paywall_service = paywall_service
        self._monetization_state = monetization_state_service or MonetizationStateService(uow_factory)

    async def get_features(self, user_id: int) -> SubscriptionFeatures:
        async with self._uow_factory() as uow:
            subscription = await uow.subscriptions.get_by_user(user_id)
            await uow.commit()

        tier = (subscription.tier if subscription else "free").lower()
        trial_tier = getattr(subscription, "trial_tier", None)
        trial_ends_at = getattr(subscription, "trial_ends_at", None)
        if trial_tier and trial_ends_at and trial_ends_at > utc_now():
            tier = trial_tier.lower()
        base = TIER_FEATURES.get(tier, TIER_FEATURES["free"])
        paywall_variant = await self._paywall_variant(user_id, tier)
        paywall_decision = await self._paywall_service.evaluate(user_id) if self._paywall_service else None
        if not subscription:
            return self._apply_paywall_variant(base, paywall_variant, paywall_decision)
        adjusted_limits = self._apply_variant_limits(
            request_limit=subscription.request_limit,
            token_limit=subscription.token_limit,
            variant=paywall_variant,
            tier=tier,
        )
        features = SubscriptionFeatures(
            tier=base.tier,
            request_limit=adjusted_limits["request_limit"],
            token_limit=adjusted_limits["token_limit"],
            tutor_depth=base.tutor_depth,
            explanation_quality=base.explanation_quality,
            personalization_level=base.personalization_level,
            paywall_variant=paywall_variant,
            trial_active=bool(paywall_decision.trial_active) if paywall_decision else False,
            trial_ends_at=paywall_decision.trial_ends_at if paywall_decision else trial_ends_at,
            usage_percent=paywall_decision.usage_percent if paywall_decision else 0,
            paywall_type=paywall_decision.paywall_type if paywall_decision else None,
            paywall_reason=paywall_decision.reason if paywall_decision else None,
            allow_access=paywall_decision.allow_access if paywall_decision else True,
        )
        return self._apply_quality_gate(features)

    async def require_feature(self, user_id: int, feature_name: str, minimum_tier: str) -> SubscriptionFeatures:
        features = await self.get_features(user_id)
        if self._tier_rank(features.tier) < self._tier_rank(minimum_tier):
            await self.record_feature_gate(
                user_id=user_id,
                feature_name=feature_name,
                allowed=False,
                current_tier=features.tier,
                required_tier=minimum_tier,
            )
        return features

    async def record_feature_gate(
        self,
        *,
        user_id: int,
        feature_name: str,
        allowed: bool,
        current_tier: str,
        required_tier: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.subscription_events.record(
                user_id=user_id,
                event_type="feature_gate_allowed" if allowed else "feature_gate_blocked",
                from_tier=current_tier,
                to_tier=required_tier,
                feature_name=feature_name,
                metadata={"allowed": allowed},
            )
            await uow.commit()

    async def upgrade_tier(self, user_id: int, tier: str) -> SubscriptionFeatures:
        target = TIER_FEATURES[tier]
        features_before = await self.get_features(user_id)
        async with self._uow_factory() as uow:
            current = await uow.subscriptions.get_by_user(user_id)
            from_tier = current.tier if current else "free"
            await uow.subscriptions.upsert(
                user_id=user_id,
                tier=tier,
                request_limit=target.request_limit,
                token_limit=target.token_limit,
            )
            await uow.subscription_events.record(
                user_id=user_id,
                event_type="tier_upgraded",
                from_tier=from_tier,
                to_tier=tier,
                metadata={"request_limit": target.request_limit, "token_limit": target.token_limit},
            )
            await uow.commit()
        if self._event_service:
            await self._event_service.track_event(
                user_id,
                "subscription_upgraded",
                {"source": "subscription_service", "from_tier": from_tier, "to_tier": tier},
            )
        if self._paywall_service:
            await self._paywall_service.register_upgrade_completed(
                user_id,
                tier=tier,
                source="subscription_service.upgrade_tier",
            )
        await self._monetization_state.mark_upgrade_completed(
            user_id=user_id,
            offer_type=features_before.paywall_variant or features_before.paywall_type,
            paywall_type=features_before.paywall_type,
            strategy=None,
            geography=None,
            tier=tier,
        )
        return target

    async def start_trial(self, user_id: int, duration_days: int | None = None) -> SubscriptionFeatures:
        features_before = await self.get_features(user_id)
        if self._paywall_service:
            await self._paywall_service.start_trial(user_id, duration_days)
        features = await self.get_features(user_id)
        await self._monetization_state.mark_trial_started(
            user_id=user_id,
            offer_type=features_before.paywall_variant or "trial",
            paywall_type=features_before.paywall_type,
            strategy=None,
            geography=None,
            trial_started_at=utc_now(),
            trial_ends_at=features.trial_ends_at,
            trial_days=duration_days,
        )
        return features

    async def register_upgrade_click(self, user_id: int, *, source: str) -> None:
        if self._paywall_service:
            await self._paywall_service.register_upgrade_click(user_id, source=source)
        features = await self.get_features(user_id)
        await self._monetization_state.record_response(
            user_id=user_id,
            event_type="paywall_accepted",
            offer_type=features.paywall_variant or features.paywall_type,
            paywall_type=features.paywall_type,
            strategy=None,
            geography=None,
            payload={"source": source},
        )

    async def conversion_metrics(self) -> ConversionMetrics:
        async with self._uow_factory() as uow:
            counts = await uow.subscription_events.counts_by_event()
            await uow.commit()
        return ConversionMetrics(counts_by_event=counts)

    def _tier_rank(self, tier: str) -> int:
        return {"free": 0, "pro": 1, "premium": 2}.get(tier, 0)

    async def _paywall_variant(self, user_id: int, tier: str) -> str | None:
        if tier != "free":
            return None
        if not self._experiments or not await self._experiments.has_experiment("paywall_offer"):
            return None
        return await self._experiments.assign(user_id, "paywall_offer")

    def _apply_paywall_variant(
        self,
        base: SubscriptionFeatures,
        variant: str | None,
        decision=None,
    ) -> SubscriptionFeatures:
        adjusted_limits = self._apply_variant_limits(
            request_limit=base.request_limit,
            token_limit=base.token_limit,
            variant=variant,
            tier=base.tier,
        )
        features = SubscriptionFeatures(
            tier=base.tier,
            request_limit=adjusted_limits["request_limit"],
            token_limit=adjusted_limits["token_limit"],
            tutor_depth=base.tutor_depth,
            explanation_quality=base.explanation_quality,
            personalization_level=base.personalization_level,
            paywall_variant=variant,
            trial_active=bool(decision.trial_active) if decision else False,
            trial_ends_at=decision.trial_ends_at if decision else None,
            usage_percent=decision.usage_percent if decision else 0,
            paywall_type=decision.paywall_type if decision else None,
            paywall_reason=decision.reason if decision else None,
            allow_access=decision.allow_access if decision else True,
        )
        return self._apply_quality_gate(features)

    def _apply_variant_limits(
        self,
        *,
        request_limit: int,
        token_limit: int,
        variant: str | None,
        tier: str,
    ) -> dict[str, int]:
        if tier != "free":
            return {"request_limit": request_limit, "token_limit": token_limit}
        if variant == "soft_paywall":
            return {
                "request_limit": int(request_limit * 1.2),
                "token_limit": int(token_limit * 1.2),
            }
        if variant == "hard_paywall":
            return {
                "request_limit": max(1, int(request_limit * 0.8)),
                "token_limit": max(1, int(token_limit * 0.8)),
            }
        return {"request_limit": request_limit, "token_limit": token_limit}

    def _apply_quality_gate(self, features: SubscriptionFeatures) -> SubscriptionFeatures:
        if features.paywall_type != "soft_paywall":
            return features
        return SubscriptionFeatures(
            tier=features.tier,
            request_limit=features.request_limit,
            token_limit=features.token_limit,
            tutor_depth="basic",
            explanation_quality="basic",
            personalization_level=features.personalization_level,
            paywall_variant=features.paywall_variant,
            trial_active=features.trial_active,
            trial_ends_at=features.trial_ends_at,
            usage_percent=features.usage_percent,
            paywall_type=features.paywall_type,
            paywall_reason=features.paywall_reason,
            allow_access=features.allow_access,
        )
