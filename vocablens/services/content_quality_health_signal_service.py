from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    CONTENT_QUALITY_ACTIVE_ALERTS,
    CONTENT_QUALITY_HEALTH_ALERTS,
    CONTENT_QUALITY_HEALTH_RATE,
    CONTENT_QUALITY_HEALTH_SCOPES,
    CONTENT_QUALITY_HEALTH_STATUS,
    CONTENT_QUALITY_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.content_quality_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class ContentQualityHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class ContentQualityHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork], alert_sink: OpsAlertSink | None = None):
        self._uow_factory = uow_factory
        self._alert_sink = alert_sink or LoggingOpsAlertSink()

    async def evaluate_scope(self, scope_key: str = "global") -> dict[str, Any]:
        metrics = await self._metrics()
        status, alerts = self._evaluate_health(metrics)
        alert_codes = sorted(str(item.get("code") or "") for item in alerts if item.get("code"))
        previous = await self._persist_state(
            scope_key=scope_key,
            current_status=status,
            latest_alert_codes=alert_codes,
            metrics=metrics,
        )
        self._record_metrics(scope_key, status, metrics)
        await self._record_aggregate_metrics()
        await self._emit_signals(
            scope_key=scope_key,
            previous_status=previous.current_status if previous else None,
            previous_alert_codes=previous.latest_alert_codes if previous else [],
            status=status,
            alerts=alerts,
            metrics=metrics,
        )
        return {
            "scope_key": scope_key,
            "health": {
                "status": status,
                "metrics": metrics,
                "alerts": alerts,
            },
        }

    async def get_health_dashboard(self, *, limit: int = 50) -> dict[str, Any]:
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            states = await uow.content_quality_health_states.list_all()
            await uow.commit()
        rows = [
            {
                "scope_key": str(item.scope_key),
                "health_status": str(item.current_status),
                "latest_alert_codes": list(item.latest_alert_codes or []),
                "metrics": dict(item.metrics or {}),
                "last_evaluated_at": item.last_evaluated_at.isoformat() if item.last_evaluated_at else None,
            }
            for item in states
        ]
        rows.sort(key=lambda item: (self._status_rank(item["health_status"]), item["scope_key"]))
        counts_by_status: dict[str, int] = {}
        alert_counts_by_code: dict[str, int] = {}
        for row in rows:
            counts_by_status[row["health_status"]] = counts_by_status.get(row["health_status"], 0) + 1
            for code in row["latest_alert_codes"]:
                alert_counts_by_code[code] = alert_counts_by_code.get(code, 0) + 1
        return {
            "summary": {
                "total_scopes": len(rows),
                "counts_by_health_status": dict(sorted(counts_by_status.items())),
                "scopes_with_alerts": sum(1 for row in rows if row["latest_alert_codes"]),
                "alert_counts_by_code": dict(sorted(alert_counts_by_code.items())),
                "latest_evaluated_at": max((row["last_evaluated_at"] for row in rows if row["last_evaluated_at"]), default=None),
            },
            "attention": [row for row in rows if row["health_status"] != "healthy"][:normalized_limit],
            "scopes": rows[:normalized_limit],
        }

    async def _metrics(self) -> dict[str, Any]:
        window_start = utc_now() - timedelta(days=7)
        async with self._uow_factory() as uow:
            checks = await uow.content_quality_checks.list_since(window_start, limit=5000)
            await uow.commit()

        total_checks = len(checks)
        rejected_checks = [item for item in checks if str(getattr(item, "status", "") or "") == "rejected"]
        ambiguous_prompt_checks = 0
        weak_distractor_checks = 0
        target_contract_failures = 0
        answer_contract_failures = 0
        total_score = 0.0
        for check in checks:
            total_score += float(getattr(check, "score", 0.0) or 0.0)
            for violation in list(getattr(check, "violations", []) or []):
                code = str((violation or {}).get("code") or "")
                if code == "ambiguous_prompt":
                    ambiguous_prompt_checks += 1
                elif code == "weak_distractors":
                    weak_distractor_checks += 1
                elif code == "target_contract_invalid":
                    target_contract_failures += 1
                elif code == "answer_contract_invalid":
                    answer_contract_failures += 1
        return {
            "checks_7d": total_checks,
            "rejected_checks_7d": len(rejected_checks),
            "rejection_rate_percent": round((len(rejected_checks) / total_checks) * 100.0, 2) if total_checks else 0.0,
            "ambiguous_prompt_checks_7d": ambiguous_prompt_checks,
            "weak_distractor_checks_7d": weak_distractor_checks,
            "target_contract_failures_7d": target_contract_failures,
            "answer_contract_failures_7d": answer_contract_failures,
            "average_quality_score": round(total_score / total_checks, 3) if total_checks else 1.0,
        }

    def _evaluate_health(self, metrics: dict[str, Any]):
        total_checks = int(metrics.get("checks_7d", 0) or 0)
        rejection_rate = float(metrics.get("rejection_rate_percent", 0.0) or 0.0)
        ambiguous_prompt_checks = int(metrics.get("ambiguous_prompt_checks_7d", 0) or 0)
        weak_distractor_checks = int(metrics.get("weak_distractor_checks_7d", 0) or 0)
        target_contract_failures = int(metrics.get("target_contract_failures_7d", 0) or 0)
        answer_contract_failures = int(metrics.get("answer_contract_failures_7d", 0) or 0)

        alerts: list[dict[str, Any]] = []
        if total_checks >= 10 and rejection_rate >= 15.0:
            alerts.append(
                {
                    "code": "content_rejection_rate_high",
                    "severity": "critical",
                    "message": "Content lint rejection rate is materially above the acceptable range.",
                }
            )
        elif total_checks >= 10 and rejection_rate >= 5.0:
            alerts.append(
                {
                    "code": "content_rejection_rate_high",
                    "severity": "warning",
                    "message": "Content lint rejection rate is above the expected range.",
                }
            )
        if target_contract_failures > 0:
            alerts.append(
                {
                    "code": "target_contract_failures_detected",
                    "severity": "critical",
                    "message": "At least one content artifact failed the target contract checks.",
                }
            )
        if answer_contract_failures > 0:
            alerts.append(
                {
                    "code": "answer_contract_failures_detected",
                    "severity": "critical",
                    "message": "At least one content artifact failed the answer contract checks.",
                }
            )
        if ambiguous_prompt_checks > 0:
            alerts.append(
                {
                    "code": "ambiguous_prompts_detected",
                    "severity": "warning",
                    "message": "Ambiguous prompts were detected in generated content.",
                }
            )
        if weak_distractor_checks > 0:
            alerts.append(
                {
                    "code": "weak_distractors_detected",
                    "severity": "warning",
                    "message": "Distractor quality drift was detected in generated content.",
                }
            )

        status = "healthy"
        if any(item["severity"] == "critical" for item in alerts):
            status = "critical"
        elif alerts:
            status = "warning"
        return status, alerts

    async def _persist_state(
        self,
        *,
        scope_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict[str, Any],
    ) -> ContentQualityHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.content_quality_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = ContentQualityHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.content_quality_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            CONTENT_QUALITY_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "checks_7d",
            "rejected_checks_7d",
            "rejection_rate_percent",
            "ambiguous_prompt_checks_7d",
            "weak_distractor_checks_7d",
            "target_contract_failures_7d",
            "answer_contract_failures_7d",
            "average_quality_score",
        ):
            CONTENT_QUALITY_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.content_quality_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            CONTENT_QUALITY_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

    async def _emit_signals(
        self,
        *,
        scope_key: str,
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
            CONTENT_QUALITY_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            CONTENT_QUALITY_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "content_quality_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "content_quality_health_transition",
                {
                    "scope_key": scope_key,
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
            CONTENT_QUALITY_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "content_quality_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "content_quality_health_alert",
                {
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": dict(alert),
                    "metrics": dict(metrics),
                },
            )

    def _status_rank(self, status: str) -> int:
        order = {"critical": 0, "warning": 1, "healthy": 2}
        return order.get(status, 3)
