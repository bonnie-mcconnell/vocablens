from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.notification_policy_health_signal_service import NotificationPolicyHealthSignalService
from vocablens.services.notification_policy_service import NotificationPolicyService


@dataclass(frozen=True)
class NotificationLifecyclePolicy:
    lifecycle_stage: str
    lifecycle_notifications_enabled: bool
    suppression_reason: str | None


class NotificationStateService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        *,
        cooldown_hours: int = 4,
        policy_service: NotificationPolicyService | None = None,
        health_signal_service: NotificationPolicyHealthSignalService | None = None,
    ):
        self._uow_factory = uow_factory
        self._cooldown = timedelta(hours=cooldown_hours)
        self._policy_service = policy_service or NotificationPolicyService(uow_factory)
        self._health_signals = health_signal_service or NotificationPolicyHealthSignalService(uow_factory)

    async def sync_preferences(
        self,
        *,
        user_id: int,
        preferred_channel: str,
        preferred_time_of_day: int | None,
        frequency_limit: int,
    ):
        runtime_policy = await self._policy_service.current_policy()
        normalized_channel = preferred_channel if preferred_channel in {"email", "push", "in_app"} else "push"
        normalized_hour = (
            runtime_policy.default_preferred_time_of_day
            if preferred_time_of_day is None
            else max(0, min(23, int(preferred_time_of_day)))
        )
        normalized_limit = max(0, int(frequency_limit if frequency_limit is not None else runtime_policy.default_frequency_limit))
        async with self._uow_factory() as uow:
            state = await uow.notification_states.update(
                user_id,
                preferred_channel=normalized_channel,
                preferred_time_of_day=normalized_hour,
                frequency_limit=normalized_limit,
            )
            await uow.commit()
        return state

    async def apply_lifecycle_policy(
        self,
        *,
        user_id: int,
        lifecycle_stage: str,
        source: str,
        reference_id: str | None,
    ):
        runtime_policy = await self._policy_service.current_policy()
        stage_policy = await self._policy_service.lifecycle_stage_policy(
            lifecycle_stage,
            source_context="lifecycle_service.notification",
        )
        suppressed_until = None
        if not stage_policy.lifecycle_notifications_enabled and stage_policy.recovery_window_hours > 0:
            suppressed_until = utc_now() + timedelta(hours=stage_policy.recovery_window_hours)
        async with self._uow_factory() as uow:
            state = await uow.notification_states.get_or_create(user_id)
            previous_stage = str(getattr(state, "lifecycle_stage", "") or "")
            previous_policy = dict(getattr(state, "lifecycle_policy", {}) or {})
            updated = await uow.notification_states.update(
                user_id,
                lifecycle_stage=lifecycle_stage,
                lifecycle_policy_version=runtime_policy.policy_version,
                lifecycle_policy={
                    "lifecycle_notifications_enabled": stage_policy.lifecycle_notifications_enabled,
                    "recovery_window_hours": stage_policy.recovery_window_hours,
                },
                suppression_reason=stage_policy.suppression_reason,
                suppressed_until=suppressed_until,
            )
            if previous_stage != lifecycle_stage or previous_policy != dict(updated.lifecycle_policy or {}):
                await uow.notification_suppression_events.create(
                    user_id=user_id,
                    event_type="lifecycle_policy_updated",
                    source=source,
                    reference_id=reference_id,
                    policy_key=runtime_policy.policy_key,
                    policy_version=runtime_policy.policy_version,
                    lifecycle_stage=lifecycle_stage,
                    suppression_reason=stage_policy.suppression_reason,
                    suppressed_until=suppressed_until,
                    payload=dict(updated.lifecycle_policy or {}),
                )
            await uow.commit()
        if previous_stage != lifecycle_stage or previous_policy != dict(updated.lifecycle_policy or {}):
            await self._health_signals.evaluate_policy(runtime_policy.policy_key)
        return updated

    async def record_delivery(
        self,
        *,
        user_id: int,
        category: str,
        channel: str,
        status: str,
        policy_key: str | None,
        policy_version: str | None,
        reference_id: str | None = None,
        delivered_at: datetime | None = None,
    ):
        now = delivered_at or utc_now()
        runtime_policy = await self._policy_service.current_policy()
        async with self._uow_factory() as uow:
            state = await uow.notification_states.get_or_create(user_id)
            delivery_day = now.date().isoformat()
            current_day = str(getattr(state, "sent_count_day", "") or "")
            sent_count_today = int(getattr(state, "sent_count_today", 0) or 0)
            if current_day != delivery_day:
                sent_count_today = 0
            if status == "sent":
                sent_count_today += 1
            updated = await uow.notification_states.update(
                user_id,
                sent_count_day=delivery_day,
                sent_count_today=sent_count_today,
                cooldown_until=now + timedelta(hours=runtime_policy.cooldown_hours)
                if status == "sent"
                else getattr(state, "cooldown_until", None),
                last_sent_at=now if status == "sent" else getattr(state, "last_sent_at", None),
                last_delivery_channel=channel,
                last_delivery_status=status,
                last_delivery_category=category,
                last_reference_id=reference_id,
                lifecycle_policy_version=policy_version or getattr(state, "lifecycle_policy_version", None),
            )
            await uow.commit()
        return updated

    async def record_decision(
        self,
        *,
        user_id: int,
        reason: str,
        reference_id: str | None,
        source_context: str,
    ):
        now = utc_now()
        runtime_policy = await self._policy_service.current_policy()
        async with self._uow_factory() as uow:
            state = await uow.notification_states.update(
                user_id,
                last_decision_at=now,
                last_decision_reason=reason,
                last_reference_id=reference_id,
            )
            if "lifecycle_service" in source_context and reason:
                lifecycle_policy = dict(getattr(state, "lifecycle_policy", {}) or {})
                if lifecycle_policy.get("lifecycle_notifications_enabled") is False:
                    await uow.notification_suppression_events.create(
                        user_id=user_id,
                        event_type="lifecycle_notification_suppressed",
                        source=source_context,
                        reference_id=reference_id,
                        policy_key=runtime_policy.policy_key,
                        policy_version=runtime_policy.policy_version,
                        lifecycle_stage=getattr(state, "lifecycle_stage", None),
                        suppression_reason=reason,
                        suppressed_until=getattr(state, "suppressed_until", None),
                        payload={
                            "lifecycle_policy": lifecycle_policy,
                        },
                        created_at=now,
                    )
            await uow.commit()
        if "lifecycle_service" in source_context and reason:
            await self._health_signals.evaluate_policy(runtime_policy.policy_key)
        return state
