from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    EXPERIMENT_ACTIVE_ALERTS,
    EXPERIMENT_HEALTH_ALERTS,
    EXPERIMENT_HEALTH_EXPERIMENTS,
    EXPERIMENT_HEALTH_RATE,
    EXPERIMENT_HEALTH_STATUS,
    EXPERIMENT_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.experiment_registry_service import ExperimentRegistryService


logger = get_logger("vocablens.experiment_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class ExperimentHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class ExperimentHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork], alert_sink: OpsAlertSink | None = None):
        self._uow_factory = uow_factory
        self._registry_service = ExperimentRegistryService(uow_factory)
        self._alert_sink = alert_sink or LoggingOpsAlertSink()

    async def evaluate_experiment(self, experiment_key: str) -> dict[str, Any]:
        report = await self._registry_service.get_operator_report(experiment_key, limit=100)
        experiment = dict(report.get("experiment") or {})
        health = dict(experiment.get("health") or {})
        attribution = dict(experiment.get("attribution_summary") or {})
        status, metrics, alerts = self._evaluate_health(experiment=experiment, health=health, attribution=attribution)
        alert_codes = sorted(str(item.get("code") or "") for item in alerts if item.get("code"))

        previous = await self._persist_state(
            experiment_key=experiment_key,
            current_status=status,
            latest_alert_codes=alert_codes,
            metrics=metrics,
        )
        self._record_metrics(experiment_key, status, metrics)
        await self._record_aggregate_metrics()
        await self._emit_signals(
            experiment_key=experiment_key,
            previous_status=previous.current_status if previous else None,
            previous_alert_codes=previous.latest_alert_codes if previous else [],
            status=status,
            alerts=alerts,
            metrics=metrics,
        )
        experiment["ops_health"] = {
            "status": status,
            "metrics": metrics,
            "alerts": alerts,
        }
        return {"experiment": experiment}

    def _evaluate_health(self, *, experiment: dict[str, Any], health: dict[str, Any], attribution: dict[str, Any]):
        assignment_count = int(health.get("assignment_count", 0) or 0)
        exposure_count = int(health.get("exposure_count", 0) or 0)
        exposure_gap = int(health.get("exposure_gap", 0) or 0)
        exposure_coverage = float(health.get("exposure_coverage_percent", 100.0) or 100.0)
        users = int(attribution.get("users", 0) or 0)
        converted_users = int(attribution.get("converted_users", 0) or 0)
        conversion_rate = round((converted_users / users) * 100.0, 2) if users > 0 else 0.0

        metrics = {
            "assignment_count": assignment_count,
            "exposure_count": exposure_count,
            "exposure_gap": exposure_gap,
            "exposure_coverage_percent": exposure_coverage,
            "attributed_users": users,
            "converted_users": converted_users,
            "conversion_rate_percent": conversion_rate,
        }
        alerts: list[dict[str, Any]] = []
        if assignment_count >= 5 and exposure_count == 0:
            alerts.append(
                {
                    "code": "no_exposures_recorded",
                    "severity": "critical",
                    "message": "Assignments exist but no exposures were persisted.",
                }
            )
        elif assignment_count >= 5 and exposure_coverage < 95.0:
            alerts.append(
                {
                    "code": "exposure_coverage_low",
                    "severity": "warning",
                    "message": "Exposure coverage dropped below the acceptable threshold.",
                }
            )
        if exposure_gap >= 10:
            alerts.append(
                {
                    "code": "exposure_gap_high",
                    "severity": "critical",
                    "message": "Assignment and exposure counts diverged beyond the allowed gap.",
                }
            )

        status = "healthy"
        if any(item["severity"] == "critical" for item in alerts):
            status = "critical"
        elif alerts:
            status = "warning"
        return status, metrics, alerts

    async def _persist_state(
        self,
        *,
        experiment_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict[str, Any],
    ) -> ExperimentHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.experiment_health_states.get(experiment_key)
            previous = None
            if previous_row is not None:
                previous = ExperimentHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.experiment_health_states.upsert(
                experiment_key=experiment_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, experiment_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            EXPERIMENT_HEALTH_STATUS.labels(experiment_key=experiment_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "assignment_count",
            "exposure_count",
            "exposure_gap",
            "exposure_coverage_percent",
            "conversion_rate_percent",
        ):
            EXPERIMENT_HEALTH_RATE.labels(experiment_key=experiment_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.experiment_health_states.list_all()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            EXPERIMENT_HEALTH_EXPERIMENTS.labels(status=candidate).set(float(counts[candidate]))

    async def _emit_signals(
        self,
        *,
        experiment_key: str,
        previous_status: str | None,
        previous_alert_codes: list[str],
        status: str,
        alerts: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        alert_counts = {"warning": 0, "critical": 0}
        for alert in alerts:
            severity = str(alert.get("severity") or "warning")
            if severity in alert_counts:
                alert_counts[severity] += 1
        for severity, count in alert_counts.items():
            EXPERIMENT_ACTIVE_ALERTS.labels(experiment_key=experiment_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            EXPERIMENT_HEALTH_TRANSITIONS.labels(
                experiment_key=experiment_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "experiment_health_transition",
                extra={
                    "experiment_key": experiment_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "experiment_health_transition",
                {
                    "experiment_key": experiment_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": dict(metrics),
                },
            )

        previous_codes = set(previous_alert_codes)
        for alert in alerts:
            code = str(alert.get("code") or "")
            severity = str(alert.get("severity") or "warning")
            if not code or code in previous_codes:
                continue
            EXPERIMENT_HEALTH_ALERTS.labels(
                experiment_key=experiment_key,
                code=code,
                severity=severity,
            ).inc()
            logger.warning(
                "experiment_health_alert",
                extra={
                    "experiment_key": experiment_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "experiment_health_alert",
                {
                    "experiment_key": experiment_key,
                    "code": code,
                    "severity": severity,
                    "alert": dict(alert),
                    "metrics": dict(metrics),
                },
            )
