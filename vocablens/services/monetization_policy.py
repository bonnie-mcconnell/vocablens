from __future__ import annotations

from vocablens.services.business_metrics_service import TIER_MONTHLY_PRICES
from vocablens.services.report_models import (
    MonetizationBusinessContext,
    MonetizationPricing,
    MonetizationTrigger,
    MonetizationValueDisplay,
)


GEOGRAPHY_MULTIPLIERS = {
    "global": 1.0,
    "us": 1.0,
    "ca": 1.0,
    "uk": 1.0,
    "au": 1.0,
    "nz": 1.0,
    "eu": 1.05,
    "latam": 0.7,
    "in": 0.45,
    "india": 0.45,
    "sea": 0.65,
}


class MonetizationPolicy:
    def normalize_geography(self, geography: str | None) -> str:
        if not geography:
            return "global"
        normalized = geography.strip().lower()
        return normalized if normalized in GEOGRAPHY_MULTIPLIERS else "global"

    def build_pricing(
        self,
        *,
        paywall,
        lifecycle,
        onboarding_state: dict | None,
        engagement_state,
        business_metrics: dict,
        geography: str,
    ) -> MonetizationPricing:
        base_monthly = float(TIER_MONTHLY_PRICES["pro"])
        geography_multiplier = GEOGRAPHY_MULTIPLIERS.get(geography, 1.0)
        engagement_multiplier = self._engagement_multiplier(
            lifecycle.stage,
            paywall.user_segment,
            engagement_state=engagement_state,
        )
        pricing_multiplier = self._pricing_variant_multiplier(paywall.pricing_variant)
        monthly_price = round(base_monthly * geography_multiplier * engagement_multiplier * pricing_multiplier, 2)

        discount_percent = self._discount_percent(
            lifecycle_stage=lifecycle.stage,
            user_segment=paywall.user_segment,
            onboarding_state=onboarding_state,
        )
        discounted_monthly = round(monthly_price * (1 - discount_percent / 100), 2)

        revenue = business_metrics.get("revenue", {})
        ltv = float(revenue.get("ltv", 0.0) or 0.0)
        mrr = float(revenue.get("mrr", 0.0) or 0.0)
        annual_savings_percent = 20 if (
            float(getattr(engagement_state, "momentum_score", 0.0) or 0.0) >= 0.6
            and ltv >= 300
            and mrr >= 1000
        ) else 25
        annual_price = round(monthly_price * 12 * (1 - annual_savings_percent / 100), 2)
        annual_monthly_equivalent = round(annual_price / 12, 2)

        return MonetizationPricing(
            geography=geography,
            monthly_price=monthly_price,
            discounted_monthly_price=discounted_monthly,
            discount_percent=discount_percent,
            annual_price=annual_price,
            annual_monthly_equivalent=annual_monthly_equivalent,
            annual_savings_percent=annual_savings_percent,
            pricing_variant=paywall.pricing_variant,
            annual_anchor_message=(
                f"Monthly is {monthly_price:.2f}; annual works out to {annual_monthly_equivalent:.2f} per month."
            ),
            business_context=MonetizationBusinessContext(ltv=round(ltv, 2), mrr=round(mrr, 2)),
        )

    def offer_type(self, *, paywall, lifecycle, onboarding_state: dict | None) -> str:
        if paywall.trial_active:
            return "none"
        onboarding_paywall = (onboarding_state or {}).get("paywall", {})
        if onboarding_paywall.get("trial_recommended") or paywall.trial_recommended:
            return "trial"
        if lifecycle.stage in {"at_risk", "churned"} or paywall.user_segment == "low_engagement":
            return "discount"
        if lifecycle.stage == "engaged" or paywall.user_segment == "high_intent":
            return "annual_anchor"
        return "none"

    def should_show_paywall(self, *, paywall, lifecycle, onboarding_step: str | None) -> bool:
        if not paywall.show_paywall:
            return False
        if onboarding_step in {"identity_selection", "personalization", "instant_wow_moment", "progress_illusion"}:
            return False
        if lifecycle.stage == "new_user" and onboarding_step not in {"soft_paywall", "habit_lock_in", "completed"}:
            return False
        return True

    def trigger_payload(self, *, paywall, lifecycle, onboarding_step: str | None, show_paywall: bool) -> MonetizationTrigger:
        return MonetizationTrigger(
            show_now=show_paywall,
            trigger_variant=paywall.trigger_variant,
            trigger_reason=paywall.reason,
            lifecycle_stage=lifecycle.stage,
            onboarding_step=onboarding_step,
            timing_policy="deferred_for_activation"
            if paywall.show_paywall and not show_paywall
            else "adaptive_paywall",
        )

    def value_display(
        self,
        *,
        paywall,
        lifecycle,
        onboarding_state: dict | None,
        learning_state,
        progress_state,
        offer_type: str,
    ) -> MonetizationValueDisplay:
        progress_illusion = (onboarding_state or {}).get("progress_illusion", {})
        mastery = float(getattr(learning_state, "mastery_percent", 0.0) or 0.0)
        xp = int(getattr(progress_state, "xp", 0) or 0)
        level = int(getattr(progress_state, "level", 1) or 1)
        locked_progress_percent = max(
            int(mastery),
            int(paywall.usage_percent or 0),
            20 if offer_type != "none" else 0,
        )
        highlight = "Keep the progress you have already built."
        if lifecycle.stage == "engaged":
            highlight = "Unlock the full system while the user is already engaged."
        elif lifecycle.stage in {"at_risk", "churned"}:
            highlight = "Protect the streak and saved progress before they slip."

        locked_features = [
            "Unlimited tutor rounds",
            "Full adaptive review queue",
            "Detailed progress insights",
            f"Keep your {xp} XP and level {level} momentum compounding",
        ]
        if progress_illusion:
            locked_features.append("Keep your onboarding streak and fast XP gains")

        return MonetizationValueDisplay(
            show_locked_progress=offer_type != "none" or paywall.show_paywall,
            locked_progress_percent=min(99, locked_progress_percent),
            locked_features=locked_features,
            highlight=highlight,
            usage_percent=paywall.usage_percent,
        )

    def strategy(self, *, paywall, offer_type: str, geography: str) -> str:
        return f"{paywall.strategy}:{offer_type}:{geography}"

    def _engagement_multiplier(self, lifecycle_stage: str, user_segment: str, *, engagement_state) -> float:
        momentum = float(getattr(engagement_state, "momentum_score", 0.0) or 0.0)
        if lifecycle_stage in {"at_risk", "churned"} or user_segment == "low_engagement":
            return 0.9 if momentum >= 0.4 else 0.85
        if lifecycle_stage == "engaged" or user_segment == "high_intent":
            return 1.02 if momentum >= 0.7 else 1.0
        if lifecycle_stage == "new_user":
            return 0.95
        return 0.97

    def _pricing_variant_multiplier(self, pricing_variant: str) -> float:
        return {
            "standard": 1.0,
            "value_anchor": 1.0,
            "premium_anchor": 1.08,
            "discount_focus": 0.9,
        }.get(pricing_variant, 1.0)

    def _discount_percent(self, *, lifecycle_stage: str, user_segment: str, onboarding_state: dict | None) -> int:
        onboarding_step = onboarding_state.get("current_step") if onboarding_state else None
        if lifecycle_stage in {"at_risk", "churned"} or user_segment == "low_engagement":
            return 20
        if onboarding_step == "soft_paywall":
            return 10
        if lifecycle_stage == "new_user":
            return 5
        return 0
