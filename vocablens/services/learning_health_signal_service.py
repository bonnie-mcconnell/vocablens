from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import DecisionTraceORM, UserLearningStateORM
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    LEARNING_ACTIVE_ALERTS,
    LEARNING_HEALTH_ALERTS,
    LEARNING_HEALTH_RATE,
    LEARNING_HEALTH_SCOPES,
    LEARNING_HEALTH_STATUS,
    LEARNING_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.learning_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class LearningHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class LearningHealthSignalService:
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
            states = await uow.learning_health_states.list_all()
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
            traces = (
                await uow.session.execute(
                    select(DecisionTraceORM).where(
                        DecisionTraceORM.created_at >= window_start,
                        DecisionTraceORM.trace_type.in_(["lesson_recommendation", "knowledge_update"]),
                    )
                )
            ).scalars().all()
            learning_states = (
                await uow.session.execute(select(UserLearningStateORM))
            ).scalars().all()
            await uow.commit()

        recommendation_traces = [
            item for item in traces if str(getattr(item, "trace_type", "") or "") == "lesson_recommendation"
        ]
        knowledge_update_traces = [
            item for item in traces if str(getattr(item, "trace_type", "") or "") == "knowledge_update"
        ]

        missing_target_recommendations = 0
        generic_target_recommendations = 0
        for trace in recommendation_traces:
            outputs = dict(getattr(trace, "outputs", {}) or {})
            action = str(outputs.get("action") or "")
            target = outputs.get("target")
            if action in {"learn_new_word", "practice_grammar", "conversation_drill"} and not target:
                missing_target_recommendations += 1
            if str(target or "").lower() in {"", "general", "vocabulary"}:
                generic_target_recommendations += 1

        low_mastery_without_weak_areas_users = sum(
            1
            for state in learning_states
            if float(getattr(state, "mastery_percent", 0.0) or 0.0) < 30.0
            and not list(getattr(state, "weak_areas", []) or [])
        )
        recommendation_count = len(recommendation_traces)
        knowledge_update_count = len(knowledge_update_traces)
        return {
            "recommendations_7d": recommendation_count,
            "knowledge_updates_7d": knowledge_update_count,
            "recommendation_update_coverage_percent": round((knowledge_update_count / recommendation_count) * 100.0, 2) if recommendation_count else 100.0,
            "missing_target_recommendations_7d": missing_target_recommendations,
            "missing_target_rate_percent": round((missing_target_recommendations / recommendation_count) * 100.0, 2) if recommendation_count else 0.0,
            "generic_target_recommendations_7d": generic_target_recommendations,
            "generic_target_rate_percent": round((generic_target_recommendations / recommendation_count) * 100.0, 2) if recommendation_count else 0.0,
            "low_mastery_without_weak_areas_users": low_mastery_without_weak_areas_users,
        }

    def _evaluate_health(self, metrics: dict[str, Any]):
        recommendation_count = int(metrics.get("recommendations_7d", 0) or 0)
        update_coverage = float(metrics.get("recommendation_update_coverage_percent", 100.0) or 100.0)
        missing_target_rate = float(metrics.get("missing_target_rate_percent", 0.0) or 0.0)
        generic_target_rate = float(metrics.get("generic_target_rate_percent", 0.0) or 0.0)
        low_mastery_without_weak_areas_users = int(metrics.get("low_mastery_without_weak_areas_users", 0) or 0)

        alerts: list[dict[str, Any]] = []
        if recommendation_count >= 20 and update_coverage < 30.0:
            alerts.append(
                {
                    "code": "knowledge_update_coverage_low",
                    "severity": "critical",
                    "message": "Recommendations are not converting into canonical knowledge updates.",
                }
            )
        elif recommendation_count >= 20 and update_coverage < 50.0:
            alerts.append(
                {
                    "code": "knowledge_update_coverage_low",
                    "severity": "warning",
                    "message": "Knowledge update coverage dropped below the expected range.",
                }
            )
        if recommendation_count >= 20 and missing_target_rate > 10.0:
            alerts.append(
                {
                    "code": "recommendation_target_missing",
                    "severity": "critical",
                    "message": "Too many learning recommendations are missing a concrete target.",
                }
            )
        elif recommendation_count >= 20 and generic_target_rate > 40.0:
            alerts.append(
                {
                    "code": "recommendation_target_generic",
                    "severity": "warning",
                    "message": "Learning recommendations are drifting toward generic targets too often.",
                }
            )
        if low_mastery_without_weak_areas_users > 0:
            alerts.append(
                {
                    "code": "weak_area_detection_missing",
                    "severity": "warning",
                    "message": "At least one low-mastery user has no recorded weak areas.",
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
    ) -> LearningHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.learning_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = LearningHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.learning_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            LEARNING_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "recommendations_7d",
            "knowledge_updates_7d",
            "recommendation_update_coverage_percent",
            "missing_target_rate_percent",
            "generic_target_rate_percent",
            "low_mastery_without_weak_areas_users",
        ):
            LEARNING_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.learning_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            LEARNING_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            LEARNING_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            LEARNING_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "learning_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "learning_health_transition",
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
            LEARNING_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "learning_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "learning_health_alert",
                {
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": dict(alert),
                    "metrics": dict(metrics),
                },
            )

    def _status_rank(self, status: str) -> int:
        ranking = {"critical": 0, "warning": 1, "healthy": 2}
        return ranking.get(status, 3)
