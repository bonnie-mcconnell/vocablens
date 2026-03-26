from __future__ import annotations


class AdaptivePaywallPolicy:
    def segment_user(
        self,
        *,
        monetization_state,
        profile,
        sessions_seen: int,
        usage_ratio: float,
        wow_moment: bool,
        wow_score: float,
    ) -> str:
        viewed_paywall = int(getattr(monetization_state, "paywall_impressions", 0) or 0) > 0
        clicked_upgrade = int(getattr(monetization_state, "paywall_acceptances", 0) or 0) > 0
        drop_off_risk = float(getattr(profile, "drop_off_risk", 0.0) or 0.0)
        session_frequency = float(getattr(profile, "session_frequency", 0.0) or 0.0)
        if clicked_upgrade or viewed_paywall or wow_moment or wow_score >= 0.72 or usage_ratio >= 0.55 or sessions_seen >= 4:
            return "high_intent"
        if drop_off_risk >= 0.45 or session_frequency < 1.5 or sessions_seen <= 1:
            return "low_engagement"
        return "balanced"

    def thresholds(
        self,
        *,
        user_segment: str,
        trigger_variant: str,
        base_session_trigger: int,
        base_usage_soft_threshold: float,
        base_usage_hard_threshold: float,
    ) -> dict[str, float | int]:
        session_trigger = base_session_trigger
        soft_usage_threshold = base_usage_soft_threshold
        hard_usage_threshold = base_usage_hard_threshold

        if trigger_variant == "early":
            session_trigger -= 1
            soft_usage_threshold -= 0.1
        elif trigger_variant == "late":
            session_trigger += 2
            soft_usage_threshold += 0.1

        if user_segment == "high_intent":
            session_trigger -= 1
            soft_usage_threshold -= 0.15
        elif user_segment == "low_engagement":
            session_trigger += 2
            soft_usage_threshold += 0.1
            hard_usage_threshold += 0.05

        return {
            "session_trigger": max(1, int(session_trigger)),
            "soft_usage_threshold": max(0.2, min(0.98, soft_usage_threshold)),
            "hard_usage_threshold": max(0.5, min(1.2, hard_usage_threshold)),
        }

    def strategy_name(self, *, user_segment: str, trigger_variant: str, pricing_variant: str) -> str:
        return f"{user_segment}:{trigger_variant}:{pricing_variant}"

    def trial_days(self, trial_variant: str) -> int:
        return {
            "trial_3d": 3,
            "trial_5d": 5,
            "trial_7d": 7,
        }.get(trial_variant, 3)

    def trial_recommended(self, *, decision, wow_score: float) -> bool:
        return (
            not bool(getattr(decision, "trial_active", False))
            and wow_score >= 0.8
            and bool(getattr(decision, "allow_access", False))
        )

    def upsell_recommended(self, *, decision, wow_score: float) -> bool:
        return bool(getattr(decision, "show_paywall", False)) or wow_score >= 0.72
