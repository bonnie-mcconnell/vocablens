from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.adaptive_paywall_policy import AdaptivePaywallPolicy
from vocablens.services.event_service import EventService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.monetization_state_service import MonetizationStateService
from vocablens.services.paywall_service import PaywallDecision, PaywallService
from vocablens.services.report_models import (
    AdaptivePaywallConversionReport,
    AdaptivePaywallStrategyMetrics,
    AdaptivePaywallViewedEvent,
)


@dataclass(frozen=True)
class AdaptivePaywallDecision(PaywallDecision):
    user_segment: str
    strategy: str
    trigger_variant: str
    pricing_variant: str
    trial_days: int
    wow_score: float
    trial_recommended: bool
    upsell_recommended: bool


class AdaptivePaywallService(PaywallService):
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        event_service: EventService | None = None,
        experiment_service: ExperimentService | None = None,
        monetization_state_service: MonetizationStateService | None = None,
        *,
        session_trigger: int = 3,
        usage_soft_threshold: float = 0.8,
        usage_hard_threshold: float = 1.0,
    ):
        super().__init__(
            uow_factory,
            event_service,
            session_trigger=session_trigger,
            usage_soft_threshold=usage_soft_threshold,
            usage_hard_threshold=usage_hard_threshold,
        )
        self._uow_factory = uow_factory
        self._events = event_service
        self._experiments = experiment_service
        self._base_session_trigger = session_trigger
        self._base_usage_soft_threshold = usage_soft_threshold
        self._base_usage_hard_threshold = usage_hard_threshold
        self._policy = AdaptivePaywallPolicy()
        self._monetization_state = monetization_state_service or MonetizationStateService(uow_factory)

    async def evaluate(
        self,
        user_id: int,
        *,
        wow_moment: bool = False,
        wow_score: float | None = None,
    ) -> AdaptivePaywallDecision:
        async with self._uow_factory() as uow:
            subscription = await uow.subscriptions.get_by_user(user_id)
            used_requests, used_tokens = await uow.usage_logs.totals_for_user_day(user_id)
            profile = await uow.profiles.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            monetization_state = await uow.monetization_states.get_or_create(user_id)
            await uow.commit()

        tier = (subscription.tier if subscription else "free").lower()
        request_limit = int(getattr(subscription, "request_limit", 100) or 100)
        token_limit = int(getattr(subscription, "token_limit", 50000) or 50000)
        trial_tier = getattr(subscription, "trial_tier", None)
        trial_ends_at = getattr(subscription, "trial_ends_at", None)
        trial_active = bool(trial_tier and trial_ends_at and trial_ends_at > utc_now())
        if subscription and trial_tier and trial_ends_at and trial_ends_at <= utc_now():
            async with self._uow_factory() as uow:
                await uow.subscriptions.clear_trial(user_id)
                await uow.commit()
            trial_tier = None
            trial_ends_at = None
            trial_active = False

        sessions_seen = int(getattr(engagement_state, "total_sessions", 0) or 0)
        request_ratio = self._ratio(used_requests, request_limit)
        token_ratio = self._ratio(used_tokens, token_limit)
        usage_ratio = max(request_ratio, token_ratio)

        resolved_wow_moment = wow_moment or float(wow_score or 0.0) >= 0.65
        wow_value = round(float(wow_score or 0.0), 3)
        cooldown_until = getattr(monetization_state, "cooldown_until", None)
        in_cooldown = bool(cooldown_until and cooldown_until > utc_now())
        user_segment = self._policy.segment_user(
            monetization_state=monetization_state,
            profile=profile,
            sessions_seen=sessions_seen,
            usage_ratio=usage_ratio,
            wow_moment=resolved_wow_moment,
            wow_score=wow_value,
        )
        variants = await self._variant_bundle(user_id)
        thresholds = self._policy.thresholds(
            user_segment=user_segment,
            trigger_variant=variants["trigger_variant"],
            base_session_trigger=self._base_session_trigger,
            base_usage_soft_threshold=self._base_usage_soft_threshold,
            base_usage_hard_threshold=self._base_usage_hard_threshold,
        )
        strategy = self._policy.strategy_name(
            user_segment=user_segment,
            trigger_variant=variants["trigger_variant"],
            pricing_variant=variants["pricing_variant"],
        )

        if tier != "free" or trial_active:
            return AdaptivePaywallDecision(
                **self._decision(
                    show_paywall=False,
                    paywall_type=None,
                    reason=None,
                    used_requests=used_requests,
                    used_tokens=used_tokens,
                    request_limit=request_limit,
                    token_limit=token_limit,
                    sessions_seen=sessions_seen,
                    wow_moment_triggered=resolved_wow_moment,
                    trial_active=trial_active,
                    trial_tier=trial_tier,
                    trial_ends_at=trial_ends_at,
                    allow_access=True,
                ).__dict__,
                user_segment=user_segment,
                strategy=strategy,
                trigger_variant=variants["trigger_variant"],
                pricing_variant=variants["pricing_variant"],
                trial_days=variants["trial_days"],
                wow_score=wow_value,
                trial_recommended=False,
                upsell_recommended=False,
            )

        if in_cooldown and usage_ratio < thresholds["hard_usage_threshold"]:
            decision = self._decision(
                show_paywall=False,
                paywall_type=None,
                reason="paywall cooldown active",
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=resolved_wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=True,
            )
        elif usage_ratio >= thresholds["hard_usage_threshold"]:
            decision = self._decision(
                show_paywall=True,
                paywall_type="hard_paywall",
                reason="adaptive usage threshold reached",
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=resolved_wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=False,
            )
        elif resolved_wow_moment or sessions_seen >= thresholds["session_trigger"] or usage_ratio >= thresholds["soft_usage_threshold"]:
            reason = (
                "wow moment reached"
                if resolved_wow_moment
                else "adaptive session trigger reached"
                if sessions_seen >= thresholds["session_trigger"]
                else "adaptive usage pressure high"
            )
            decision = self._decision(
                show_paywall=True,
                paywall_type="soft_paywall",
                reason=reason,
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=resolved_wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=True,
            )
        else:
            decision = self._decision(
                show_paywall=False,
                paywall_type=None,
                reason=None,
                used_requests=used_requests,
                used_tokens=used_tokens,
                request_limit=request_limit,
                token_limit=token_limit,
                sessions_seen=sessions_seen,
                wow_moment_triggered=resolved_wow_moment,
                trial_active=False,
                trial_tier=None,
                trial_ends_at=None,
                allow_access=True,
            )

        trial_recommended = self._policy.trial_recommended(decision=decision, wow_score=wow_value)
        upsell_recommended = self._policy.upsell_recommended(decision=decision, wow_score=wow_value)
        adaptive = AdaptivePaywallDecision(
            **decision.__dict__,
            user_segment=user_segment,
            strategy=strategy,
            trigger_variant=variants["trigger_variant"],
            pricing_variant=variants["pricing_variant"],
            trial_days=variants["trial_days"],
            wow_score=wow_value,
            trial_recommended=trial_recommended,
            upsell_recommended=upsell_recommended,
        )

        if adaptive.show_paywall and self._events:
            payload = asdict(self._viewed_event_payload(adaptive))
            await self._events.track_event(
                user_id,
                "paywall_viewed",
                payload,
            )
            await self._monetization_state.record_impression(
                user_id=user_id,
                offer_type="trial" if adaptive.trial_recommended else adaptive.paywall_type,
                paywall_type=adaptive.paywall_type,
                strategy=adaptive.strategy,
                geography=None,
                payload=payload,
            )
        return adaptive

    async def start_trial(self, user_id: int, duration_days: int | None = None) -> None:
        if duration_days is None:
            duration_days = (await self._variant_bundle(user_id))["trial_days"]
        await super().start_trial(user_id, duration_days)

    async def conversion_metrics(self) -> AdaptivePaywallConversionReport:
        async with self._uow_factory() as uow:
            events = await uow.events.list_since(
                utc_now() - timedelta(days=90),
                event_types=["paywall_viewed", "upgrade_completed", "subscription_upgraded"],
                limit=50000,
            )
            await uow.commit()

        paywall_views: dict[int, list] = defaultdict(list)
        for event in events:
            if event.event_type == "paywall_viewed":
                paywall_views[event.user_id].append(event)

        strategy_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"views": 0, "upgrades": 0})
        for event in events:
            if event.event_type != "paywall_viewed":
                continue
            payload = self._payload(event)
            strategy = payload.get("strategy") or "default"
            strategy_stats[strategy]["views"] += 1

        for event in events:
            if event.event_type not in {"upgrade_completed", "subscription_upgraded"}:
                continue
            candidate_views = [
                view for view in paywall_views.get(event.user_id, [])
                if getattr(view, "created_at", None) and view.created_at <= event.created_at
            ]
            if not candidate_views:
                continue
            latest_view = max(candidate_views, key=lambda item: item.created_at)
            strategy = self._payload(latest_view).get("strategy") or "default"
            strategy_stats[strategy]["upgrades"] += 1

        strategies: list[AdaptivePaywallStrategyMetrics] = []
        for strategy, counts in sorted(strategy_stats.items()):
            views = counts["views"]
            upgrades = counts["upgrades"]
            strategies.append(
                AdaptivePaywallStrategyMetrics(
                    strategy=strategy,
                    views=views,
                    upgrades=upgrades,
                    conversion_rate=round((upgrades / max(1, views)) * 100, 1),
                )
            )
        return AdaptivePaywallConversionReport(strategies=strategies)

    async def _variant_bundle(self, user_id: int) -> dict[str, object]:
        trigger_variant = await self._assign_variant(
            user_id,
            "paywall_trigger_timing",
            default="control",
        )
        pricing_variant = await self._assign_variant(
            user_id,
            "paywall_pricing_messaging",
            default="standard",
        )
        trial_variant = await self._assign_variant(
            user_id,
            "paywall_trial_length",
            default="trial_3d",
        )
        return {
            "trigger_variant": trigger_variant,
            "pricing_variant": pricing_variant,
            "trial_days": self._policy.trial_days(trial_variant),
        }

    async def _assign_variant(self, user_id: int, experiment_key: str, *, default: str) -> str:
        if not self._experiments or not await self._experiments.has_experiment(experiment_key):
            return default
        return await self._experiments.assign(user_id, experiment_key)

    def _viewed_event_payload(self, decision: AdaptivePaywallDecision) -> AdaptivePaywallViewedEvent:
        return AdaptivePaywallViewedEvent(
            source="adaptive_paywall_service",
            type=decision.paywall_type,
            reason=decision.reason,
            usage_percent=decision.usage_percent,
            user_segment=decision.user_segment,
            strategy=decision.strategy,
            trigger_variant=decision.trigger_variant,
            pricing_variant=decision.pricing_variant,
            trial_days=decision.trial_days,
            wow_score=decision.wow_score,
            trial_recommended=decision.trial_recommended,
            upsell_recommended=decision.upsell_recommended,
        )

    def _payload(self, event) -> dict:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            return payload
        payload_json = getattr(event, "payload_json", None)
        if isinstance(payload_json, dict):
            return payload_json
        return {}
