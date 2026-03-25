from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.unit_of_work import UnitOfWork


DEFAULT_NOTIFICATION_POLICY_KEY = "default"
DEFAULT_NOTIFICATION_POLICY_VERSION = "v1"
DEFAULT_NOTIFICATION_POLICY = {
    "cooldown_hours": 4,
    "default_frequency_limit": 2,
    "default_preferred_time_of_day": 18,
    "stage_policies": {
        "new_user": {
            "lifecycle_notifications_enabled": True,
            "suppression_reason": None,
            "recovery_window_hours": 0,
        },
        "activating": {
            "lifecycle_notifications_enabled": True,
            "suppression_reason": None,
            "recovery_window_hours": 0,
        },
        "engaged": {
            "lifecycle_notifications_enabled": False,
            "suppression_reason": "engaged stage suppresses proactive lifecycle messaging",
            "recovery_window_hours": 24,
        },
        "at_risk": {
            "lifecycle_notifications_enabled": True,
            "suppression_reason": None,
            "recovery_window_hours": 0,
        },
        "churned": {
            "lifecycle_notifications_enabled": True,
            "suppression_reason": None,
            "recovery_window_hours": 0,
        },
    },
    "suppression_overrides": [
        {
            "source_context": "lifecycle_service.notification",
            "stage": "engaged",
            "lifecycle_notifications_enabled": False,
            "suppression_reason": "engaged stage suppresses proactive lifecycle messaging",
            "recovery_window_hours": 24,
        }
    ],
    "governance": {
        "min_sample_size": 25,
        "max_failed_delivery_rate_percent": 8.0,
        "max_suppression_rate_percent": 45.0,
        "max_send_rate_drop_percent": 20.0,
    },
}


@dataclass(frozen=True)
class NotificationStagePolicy:
    lifecycle_notifications_enabled: bool
    suppression_reason: str | None
    recovery_window_hours: int


@dataclass(frozen=True)
class NotificationGovernancePolicy:
    min_sample_size: int
    max_failed_delivery_rate_percent: float
    max_suppression_rate_percent: float
    max_send_rate_drop_percent: float


@dataclass(frozen=True)
class NotificationRuntimePolicy:
    policy_key: str
    policy_version: str
    cooldown_hours: int
    default_frequency_limit: int
    default_preferred_time_of_day: int
    stage_policies: dict[str, NotificationStagePolicy]
    suppression_overrides: tuple[dict[str, Any], ...]
    governance: NotificationGovernancePolicy


class NotificationPolicyService:
    def __init__(self, uow_factory: type[UnitOfWork], *, policy_key: str = DEFAULT_NOTIFICATION_POLICY_KEY):
        self._uow_factory = uow_factory
        self._policy_key = policy_key

    async def current_policy(self) -> NotificationRuntimePolicy:
        async with self._uow_factory() as uow:
            registry = await uow.notification_policy_registries.get(self._policy_key)
            await uow.commit()
        if registry is None or bool(getattr(registry, "is_killed", False)) or str(getattr(registry, "status", "")) != "active":
            return self._policy_from_config(DEFAULT_NOTIFICATION_POLICY_KEY, DEFAULT_NOTIFICATION_POLICY)
        return self._policy_from_config(str(registry.policy_key), dict(getattr(registry, "policy", {}) or {}))

    async def lifecycle_stage_policy(self, stage: str, *, source_context: str) -> NotificationStagePolicy:
        policy = await self.current_policy()
        resolved = policy.stage_policies.get(stage) or policy.stage_policies.get("new_user") or NotificationStagePolicy(
            lifecycle_notifications_enabled=True,
            suppression_reason=None,
            recovery_window_hours=0,
        )
        for override in policy.suppression_overrides:
            if str(override.get("source_context") or "") != source_context:
                continue
            if str(override.get("stage") or "") != stage:
                continue
            resolved = NotificationStagePolicy(
                lifecycle_notifications_enabled=bool(
                    override.get("lifecycle_notifications_enabled", resolved.lifecycle_notifications_enabled)
                ),
                suppression_reason=override.get("suppression_reason", resolved.suppression_reason),
                recovery_window_hours=max(0, int(override.get("recovery_window_hours", resolved.recovery_window_hours) or 0)),
            )
        return resolved

    def _policy_from_config(self, policy_key: str, config: dict[str, Any]) -> NotificationRuntimePolicy:
        payload = dict(DEFAULT_NOTIFICATION_POLICY)
        payload.update({key: value for key, value in dict(config or {}).items() if key in payload})
        stage_policies: dict[str, NotificationStagePolicy] = {}
        raw_stage_policies = dict(payload.get("stage_policies") or {})
        for stage, values in raw_stage_policies.items():
            stage_values = dict(values or {})
            stage_policies[str(stage)] = NotificationStagePolicy(
                lifecycle_notifications_enabled=bool(stage_values.get("lifecycle_notifications_enabled", True)),
                suppression_reason=stage_values.get("suppression_reason"),
                recovery_window_hours=max(0, int(stage_values.get("recovery_window_hours", 0) or 0)),
            )
        return NotificationRuntimePolicy(
            policy_key=policy_key,
            policy_version=DEFAULT_NOTIFICATION_POLICY_VERSION,
            cooldown_hours=max(1, int(payload.get("cooldown_hours", 4) or 4)),
            default_frequency_limit=max(0, int(payload.get("default_frequency_limit", 2) or 0)),
            default_preferred_time_of_day=max(0, min(23, int(payload.get("default_preferred_time_of_day", 18) or 18))),
            stage_policies=stage_policies,
            suppression_overrides=tuple(dict(item or {}) for item in list(payload.get("suppression_overrides") or [])),
            governance=self._governance_from_payload(dict(payload.get("governance") or {})),
        )

    def _governance_from_payload(self, payload: dict[str, Any]) -> NotificationGovernancePolicy:
        defaults = dict(DEFAULT_NOTIFICATION_POLICY.get("governance") or {})
        defaults.update(dict(payload or {}))
        return NotificationGovernancePolicy(
            min_sample_size=max(1, int(defaults.get("min_sample_size", 25) or 25)),
            max_failed_delivery_rate_percent=max(0.0, float(defaults.get("max_failed_delivery_rate_percent", 8.0) or 0.0)),
            max_suppression_rate_percent=max(0.0, float(defaults.get("max_suppression_rate_percent", 45.0) or 0.0)),
            max_send_rate_drop_percent=max(0.0, float(defaults.get("max_send_rate_drop_percent", 20.0) or 0.0)),
        )
