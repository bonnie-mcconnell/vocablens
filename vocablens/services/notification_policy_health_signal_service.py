from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    NOTIFICATION_POLICY_HEALTH_ALERTS,
    NOTIFICATION_POLICY_HEALTH_RATE,
    NOTIFICATION_POLICY_HEALTH_STATUS,
    NOTIFICATION_POLICY_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.notification_policy_registry_service import NotificationPolicyRegistryService


logger = get_logger("vocablens.notification_policy_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class NotificationPolicyHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class NotificationPolicyHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory
        self._registry_service = NotificationPolicyRegistryService(uow_factory)

    async def evaluate_policy(self, policy_key: str) -> dict[str, Any]:
        report = await self._registry_service.get_operator_report(policy_key, limit=100)
        health = dict(report.get("health") or {})
        status = str(health.get("status") or "healthy")
        metrics = dict(health.get("metrics") or {})
        alerts = list(health.get("alerts") or [])
        alert_codes = sorted(str(item.get("code") or "") for item in alerts if item.get("code"))

        previous = await self._persist_state(
            policy_key=policy_key,
            current_status=status,
            latest_alert_codes=alert_codes,
            metrics=metrics,
        )
        self._record_metrics(policy_key, status, metrics)
        self._emit_signals(
            policy_key=policy_key,
            previous_status=previous.current_status if previous else None,
            previous_alert_codes=previous.latest_alert_codes if previous else [],
            status=status,
            alerts=alerts,
            metrics=metrics,
        )
        return report

    async def _persist_state(
        self,
        *,
        policy_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict[str, Any],
    ) -> NotificationPolicyHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.notification_policy_health_states.get(policy_key)
            previous = None
            if previous_row is not None:
                previous = NotificationPolicyHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.notification_policy_health_states.upsert(
                policy_key=policy_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, policy_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            NOTIFICATION_POLICY_HEALTH_STATUS.labels(policy_key=policy_key, status=candidate).set(
                1 if candidate == status else 0
            )
        NOTIFICATION_POLICY_HEALTH_RATE.labels(
            policy_key=policy_key,
            metric="failed_delivery_rate_percent",
        ).set(float(metrics.get("failed_delivery_rate_percent", 0.0) or 0.0))
        NOTIFICATION_POLICY_HEALTH_RATE.labels(
            policy_key=policy_key,
            metric="suppression_rate_percent",
        ).set(float(metrics.get("suppression_rate_percent", 0.0) or 0.0))

    def _emit_signals(
        self,
        *,
        policy_key: str,
        previous_status: str | None,
        previous_alert_codes: list[str],
        status: str,
        alerts: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        if previous_status and previous_status != status:
            NOTIFICATION_POLICY_HEALTH_TRANSITIONS.labels(
                policy_key=policy_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "notification_policy_health_transition",
                extra={
                    "policy_key": policy_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )

        previous_codes = set(previous_alert_codes)
        for alert in alerts:
            code = str(alert.get("code") or "")
            severity = str(alert.get("severity") or "warning")
            if not code or code in previous_codes:
                continue
            NOTIFICATION_POLICY_HEALTH_ALERTS.labels(
                policy_key=policy_key,
                code=code,
                severity=severity,
            ).inc()
            logger.warning(
                "notification_policy_health_alert",
                extra={
                    "policy_key": policy_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
