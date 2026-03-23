from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.report_models import FunnelMetricsReport, FunnelStageMetrics

FunnelStage = Literal[
    "awareness",
    "value_realization",
    "usage_pressure",
    "paywall_exposure",
    "trial",
    "conversion",
    "retention",
]

FUNNEL_ORDER: tuple[FunnelStage, ...] = (
    "awareness",
    "value_realization",
    "usage_pressure",
    "paywall_exposure",
    "trial",
    "conversion",
    "retention",
)


@dataclass(frozen=True)
class FunnelState:
    stage: FunnelStage
    completed_stages: list[FunnelStage]
    next_action: str
    nudges: list[str]
    messaging: dict
    paywall: dict
    experiment_variant: str | None


class ConversionFunnelService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        paywall_service: PaywallService,
        analytics_service: AnalyticsService | None = None,
        experiment_service: ExperimentService | None = None,
    ):
        self._uow_factory = uow_factory
        self._paywall = paywall_service
        self._analytics = analytics_service
        self._experiments = experiment_service

    async def state(self, user_id: int) -> FunnelState:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=500)
            subscription = await uow.subscriptions.get_by_user(user_id)
            await uow.commit()

        paywall = await self._paywall.evaluate(user_id)
        completed = self._completed_stages(events, subscription, paywall)
        stage = completed[-1] if completed else "awareness"
        experiment_variant = await self._experiment_variant(user_id, stage)
        return FunnelState(
            stage=stage,
            completed_stages=completed,
            next_action=self._next_action(stage, paywall),
            nudges=self._nudges(stage, paywall),
            messaging=self._messaging(stage, subscription, paywall, experiment_variant),
            paywall={
                "show": paywall.show_paywall,
                "type": paywall.paywall_type,
                "reason": paywall.reason,
                "usage_percent": paywall.usage_percent,
            },
            experiment_variant=experiment_variant,
        )

    async def metrics(self) -> FunnelMetricsReport:
        async with self._uow_factory() as uow:
            users = await uow.users.list_all()
            events = await uow.events.list_since(utc_now() - timedelta(days=90), limit=50000)
            await uow.commit()

        events_by_user: dict[int, list] = {}
        for event in events:
            events_by_user.setdefault(event.user_id, []).append(event)

        stage_counts = {stage: 0 for stage in FUNNEL_ORDER}
        stage_conversions = {stage: 0 for stage in FUNNEL_ORDER}
        stage_progressions = {stage: 0 for stage in FUNNEL_ORDER}

        for user in users:
            user_events = events_by_user.get(user.id, [])
            async with self._uow_factory() as uow:
                subscription = await uow.subscriptions.get_by_user(user.id)
                await uow.commit()
            paywall = await self._paywall.evaluate(user.id)
            completed = self._completed_stages(user_events, subscription, paywall)
            completed_set = set(completed)
            converted = "conversion" in completed_set or "retention" in completed_set
            for index, stage in enumerate(FUNNEL_ORDER):
                if stage in completed_set:
                    stage_counts[stage] += 1
                    if converted:
                        stage_conversions[stage] += 1
                    if index + 1 < len(FUNNEL_ORDER) and FUNNEL_ORDER[index + 1] in completed_set:
                        stage_progressions[stage] += 1

        retention_summary = None
        if self._analytics:
            retention_summary = await self._analytics.retention_report()

        return FunnelMetricsReport(
            stages=[
                FunnelStageMetrics(
                    stage=stage,
                    users=stage_counts[stage],
                    conversion_rate=round((stage_conversions[stage] / max(1, stage_counts[stage])) * 100, 1),
                    drop_off_rate=round(
                        100.0 - ((stage_progressions[stage] / max(1, stage_counts[stage])) * 100),
                        1,
                    ) if stage != FUNNEL_ORDER[-1] else 0.0,
                )
                for stage in FUNNEL_ORDER
            ],
            retention_summary=retention_summary,
        )

    def _completed_stages(self, events, subscription, paywall) -> list[FunnelStage]:
        completed: list[FunnelStage] = []
        if self._has_session(events):
            completed.append("awareness")
        if self._has_wow(events):
            completed.append("value_realization")
        if getattr(paywall, "usage_percent", 0) >= 60 or getattr(paywall, "reason", "") in {
            "usage pressure high",
            "adaptive usage pressure high",
            "adaptive session trigger reached",
        }:
            completed.append("usage_pressure")
        if any(getattr(event, "event_type", None) == "paywall_viewed" for event in events) or getattr(paywall, "show_paywall", False):
            completed.append("paywall_exposure")
        if self._trial_active(subscription):
            completed.append("trial")
        if self._converted(subscription, events):
            completed.append("conversion")
        if self._retained_after_conversion(events):
            completed.append("retention")
        return completed or ["awareness"]

    def _has_session(self, events) -> bool:
        return any(getattr(event, "event_type", None) == "session_started" for event in events)

    def _has_wow(self, events) -> bool:
        for event in events:
            if getattr(event, "event_type", None) != "message_sent":
                continue
            payload = self._payload(event)
            if payload.get("wow_moment") or float(payload.get("wow_score", 0.0) or 0.0) >= 0.65:
                return True
        return False

    def _trial_active(self, subscription) -> bool:
        trial_ends_at = getattr(subscription, "trial_ends_at", None)
        return bool(getattr(subscription, "trial_tier", None) and trial_ends_at and trial_ends_at > utc_now())

    def _converted(self, subscription, events) -> bool:
        tier = (getattr(subscription, "tier", "free") or "free").lower() if subscription else "free"
        if tier != "free":
            return True
        return any(getattr(event, "event_type", None) in {"upgrade_completed", "subscription_upgraded"} for event in events)

    def _retained_after_conversion(self, events) -> bool:
        conversion_times = [
            event.created_at
            for event in events
            if getattr(event, "event_type", None) in {"upgrade_completed", "subscription_upgraded"}
            and getattr(event, "created_at", None) is not None
        ]
        if not conversion_times:
            return False
        converted_at = min(conversion_times)
        return any(
            getattr(event, "event_type", None) == "session_started"
            and getattr(event, "created_at", None) is not None
            and event.created_at > converted_at
            for event in events
        )

    def _next_action(self, stage: FunnelStage, paywall) -> str:
        if stage == "awareness":
            return "soft_nudge"
        if stage == "value_realization":
            return "highlight_wow_value"
        if stage == "usage_pressure":
            return "prepare_soft_paywall"
        if stage == "paywall_exposure":
            return "offer_trial" if getattr(paywall, "trial_recommended", False) else "anchor_pricing"
        if stage == "trial":
            return "convert_before_expiry"
        if stage == "conversion":
            return "retain_paid_user"
        return "reinforce_value"

    def _nudges(self, stage: FunnelStage, paywall) -> list[str]:
        if stage in {"awareness", "value_realization"}:
            return ["soft_nudge", "show_value"]
        if stage in {"usage_pressure", "paywall_exposure"}:
            return ["limited_trial_urgency", "premium_anchor", "hard_paywall" if getattr(paywall, "paywall_type", None) == "hard_paywall" else "soft_paywall"]
        if stage == "trial":
            return ["trial_countdown", "premium_anchor"]
        return ["retention_reinforcement"]

    def _messaging(self, stage: FunnelStage, subscription, paywall, experiment_variant: str | None) -> dict:
        urgency = ""
        if self._trial_active(subscription):
            urgency = "Your Pro trial is limited; unlock full access before it ends."
        elif stage in {"usage_pressure", "paywall_exposure"}:
            urgency = f"{getattr(paywall, 'usage_percent', 0)}% of today’s free usage is already used."
        anchoring = "Premium gives deeper tutor support; Pro unlocks the full core learning loop."
        if experiment_variant:
            anchoring = f"{anchoring} Active experiment: {experiment_variant}."
        return {
            "urgency_message": urgency,
            "anchoring_message": anchoring,
        }

    async def _experiment_variant(self, user_id: int, stage: FunnelStage) -> str | None:
        if not self._experiments or stage not in {"usage_pressure", "paywall_exposure", "trial"}:
            return None
        if self._experiments.has_experiment("paywall_pricing_messaging"):
            return await self._experiments.assign(user_id, "paywall_pricing_messaging")
        if self._experiments.has_experiment("paywall_offer"):
            return await self._experiments.assign(user_id, "paywall_offer")
        return None

    def _payload(self, event) -> dict:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            return payload
        payload_json = getattr(event, "payload_json", None)
        if not payload_json:
            return {}
        try:
            return json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}
