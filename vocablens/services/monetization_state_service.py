from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.monetization_health_signal_service import MonetizationHealthSignalService


class MonetizationStateService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        health_signal_service: MonetizationHealthSignalService | None = None,
    ):
        self._uow_factory = uow_factory
        self._health_signals = health_signal_service or MonetizationHealthSignalService(uow_factory)

    async def sync_decision(
        self,
        *,
        user_id: int,
        decision,
        geography: str | None,
    ):
        now = utc_now()
        async with self._uow_factory() as uow:
            state = await uow.monetization_states.get_or_create(user_id)
            trial_eligible = bool(getattr(state, "trial_eligible", True))
            if getattr(state, "trial_started_at", None) or getattr(state, "trial_ends_at", None):
                trial_eligible = False
            conversion_propensity = self._conversion_propensity(state=state, decision=decision)
            updated = await uow.monetization_states.update(
                user_id,
                current_offer_type=getattr(decision, "offer_type", None),
                last_paywall_type=getattr(decision, "paywall_type", None),
                last_paywall_reason=self._trigger_reason(decision),
                current_strategy=getattr(decision, "strategy", None),
                current_geography=geography,
                lifecycle_stage=getattr(decision, "lifecycle_stage", None),
                trial_eligible=trial_eligible,
                trial_offer_days=getattr(decision, "trial_days", None),
                conversion_propensity=conversion_propensity,
                last_offer_at=now,
                last_pricing=self._serialize(getattr(decision, "pricing", None)),
                last_trigger=self._serialize(getattr(decision, "trigger", None)),
                last_value_display=self._serialize(getattr(decision, "value_display", None)),
            )
            await uow.monetization_offer_events.record(
                user_id=user_id,
                event_type="decision_evaluated",
                offer_type=getattr(decision, "offer_type", None),
                paywall_type=getattr(decision, "paywall_type", None),
                strategy=getattr(decision, "strategy", None),
                geography=geography,
                payload={
                    "show_paywall": bool(getattr(decision, "show_paywall", False)),
                    "trial_days": getattr(decision, "trial_days", None),
                    "conversion_propensity": conversion_propensity,
                },
                created_at=now,
            )
            await uow.commit()
        await self._health_signals.evaluate_scope("global")
        return updated

    async def record_impression(
        self,
        *,
        user_id: int,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        payload: dict,
    ) -> None:
        now = utc_now()
        async with self._uow_factory() as uow:
            state = await uow.monetization_states.get_or_create(user_id)
            impressions = int(getattr(state, "paywall_impressions", 0) or 0) + 1
            fatigue_score = int(getattr(state, "fatigue_score", 0) or 0) + 1
            cooldown_until = now + timedelta(hours=min(72, 12 * fatigue_score))
            await uow.monetization_states.update(
                user_id,
                current_offer_type=offer_type,
                last_paywall_type=paywall_type,
                current_strategy=strategy,
                current_geography=geography,
                paywall_impressions=impressions,
                fatigue_score=fatigue_score,
                cooldown_until=cooldown_until,
                last_impression_at=now,
                last_offer_at=now,
            )
            await uow.monetization_offer_events.record(
                user_id=user_id,
                event_type="paywall_impression",
                offer_type=offer_type,
                paywall_type=paywall_type,
                strategy=strategy,
                geography=geography,
                payload=payload,
                created_at=now,
            )
            await uow.commit()
        await self._health_signals.evaluate_scope("global")

    async def record_response(
        self,
        *,
        user_id: int,
        event_type: str,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        payload: dict,
    ) -> None:
        now = utc_now()
        async with self._uow_factory() as uow:
            state = await uow.monetization_states.get_or_create(user_id)
            updates = {
                "current_offer_type": offer_type,
                "last_paywall_type": paywall_type,
                "current_strategy": strategy,
                "current_geography": geography,
            }
            if event_type == "paywall_dismissed":
                updates["paywall_dismissals"] = int(getattr(state, "paywall_dismissals", 0) or 0) + 1
                updates["fatigue_score"] = int(getattr(state, "fatigue_score", 0) or 0) + 2
                updates["last_dismissed_at"] = now
                updates["cooldown_until"] = now + timedelta(hours=24)
            elif event_type == "paywall_skipped":
                updates["paywall_skips"] = int(getattr(state, "paywall_skips", 0) or 0) + 1
                updates["fatigue_score"] = int(getattr(state, "fatigue_score", 0) or 0) + 1
                updates["last_skipped_at"] = now
                updates["cooldown_until"] = now + timedelta(hours=12)
            elif event_type in {"paywall_accepted", "trial_started", "upgrade_completed"}:
                updates["paywall_acceptances"] = int(getattr(state, "paywall_acceptances", 0) or 0) + 1
                updates["fatigue_score"] = max(0, int(getattr(state, "fatigue_score", 0) or 0) - 1)
                updates["last_accepted_at"] = now
                updates["cooldown_until"] = now + timedelta(days=7)
                updates["trial_eligible"] = False
            await uow.monetization_states.update(user_id, **updates)
            await uow.monetization_offer_events.record(
                user_id=user_id,
                event_type=event_type,
                offer_type=offer_type,
                paywall_type=paywall_type,
                strategy=strategy,
                geography=geography,
                payload=payload,
                created_at=now,
            )
            await uow.commit()
        await self._health_signals.evaluate_scope("global")

    async def mark_trial_started(
        self,
        *,
        user_id: int,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        trial_started_at,
        trial_ends_at,
        trial_days: int | None,
    ) -> None:
        async with self._uow_factory() as uow:
            state = await uow.monetization_states.get_or_create(user_id)
            await uow.monetization_states.update(
                user_id,
                current_offer_type=offer_type,
                last_paywall_type=paywall_type,
                current_strategy=strategy,
                current_geography=geography,
                trial_eligible=False,
                trial_started_at=trial_started_at,
                trial_ends_at=trial_ends_at,
                trial_offer_days=trial_days,
                paywall_acceptances=int(getattr(state, "paywall_acceptances", 0) or 0) + 1,
                last_accepted_at=trial_started_at,
                cooldown_until=trial_ends_at,
            )
            await uow.monetization_offer_events.record(
                user_id=user_id,
                event_type="trial_started",
                offer_type=offer_type,
                paywall_type=paywall_type,
                strategy=strategy,
                geography=geography,
                payload={
                    "trial_started_at": self._timestamp(trial_started_at),
                    "trial_ends_at": self._timestamp(trial_ends_at),
                    "trial_days": trial_days,
                },
            )
            await uow.commit()
        await self._health_signals.evaluate_scope("global")

    async def mark_upgrade_completed(
        self,
        *,
        user_id: int,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        tier: str,
    ) -> None:
        async with self._uow_factory() as uow:
            state = await uow.monetization_states.get_or_create(user_id)
            now = utc_now()
            await uow.monetization_states.update(
                user_id,
                current_offer_type=offer_type,
                last_paywall_type=paywall_type,
                current_strategy=strategy,
                current_geography=geography,
                trial_eligible=False,
                paywall_acceptances=int(getattr(state, "paywall_acceptances", 0) or 0) + 1,
                last_accepted_at=now,
                cooldown_until=now + timedelta(days=30),
            )
            await uow.monetization_offer_events.record(
                user_id=user_id,
                event_type="upgrade_completed",
                offer_type=offer_type,
                paywall_type=paywall_type,
                strategy=strategy,
                geography=geography,
                payload={"tier": tier},
            )
            await uow.commit()
        await self._health_signals.evaluate_scope("global")

    def _conversion_propensity(self, *, state, decision) -> float:
        base = 0.15
        offer_type = str(getattr(decision, "offer_type", "") or "")
        if offer_type == "trial":
            base += 0.2
        elif offer_type == "discount":
            base += 0.12
        elif offer_type == "annual_anchor":
            base += 0.08
        if bool(getattr(decision, "show_paywall", False)):
            base += 0.1
        fatigue_penalty = min(0.2, int(getattr(state, "fatigue_score", 0) or 0) * 0.03)
        trial_block = 0.1 if not bool(getattr(state, "trial_eligible", True)) and offer_type == "trial" else 0.0
        return round(max(0.0, min(1.0, base - fatigue_penalty - trial_block)), 3)

    def _serialize(self, value):
        if value is None:
            return {}
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return dict(value)
        return dict(getattr(value, "__dict__", {}) or {})

    def _trigger_reason(self, decision) -> str | None:
        trigger = getattr(decision, "trigger", None)
        if trigger is None:
            return None
        return getattr(trigger, "trigger_reason", None)

    def _timestamp(self, value) -> str | None:
        return value.isoformat() if getattr(value, "isoformat", None) else None
