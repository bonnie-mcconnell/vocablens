from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import (
    DecisionTraceORM,
    EventORM,
    LearningSessionAttemptORM,
    LearningSessionORM,
)
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    SESSION_ACTIVE_ALERTS,
    SESSION_HEALTH_ALERTS,
    SESSION_HEALTH_RATE,
    SESSION_HEALTH_SCOPES,
    SESSION_HEALTH_STATUS,
    SESSION_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.session_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class SessionHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class SessionHealthSignalService:
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
            states = await uow.session_health_states.list_all()
            window_start = utc_now() - timedelta(days=7)
            sessions = (
                await uow.session.execute(
                    select(LearningSessionORM).where(LearningSessionORM.created_at >= window_start)
                )
            ).scalars().all()
            attempts = (
                await uow.session.execute(
                    select(LearningSessionAttemptORM).where(LearningSessionAttemptORM.created_at >= window_start)
                )
            ).scalars().all()
            traces = (
                await uow.session.execute(
                    select(DecisionTraceORM).where(
                        DecisionTraceORM.created_at >= window_start,
                        DecisionTraceORM.trace_type == "session_evaluation",
                    )
                )
            ).scalars().all()
            await uow.commit()
        sessions_by_id = {str(item.session_id): item for item in sessions}
        rows = [
            {
                "scope_key": str(item.scope_key),
                "health_status": str(item.current_status),
                "latest_alert_codes": list(item.latest_alert_codes or []),
                "metrics": dict(item.metrics or {}),
                "alert_drilldowns": self._dashboard_drilldowns(
                    scope_key=str(item.scope_key),
                    latest_alert_codes=list(item.latest_alert_codes or []),
                    sessions_by_id=sessions_by_id,
                    attempts=attempts,
                    traces=traces,
                ),
                "last_evaluated_at": getattr(item, "last_evaluated_at", None).isoformat() if getattr(item, "last_evaluated_at", None) else None,
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
            sessions = (
                await uow.session.execute(
                    select(LearningSessionORM).where(LearningSessionORM.created_at >= window_start)
                )
            ).scalars().all()
            attempts = (
                await uow.session.execute(
                    select(LearningSessionAttemptORM).where(LearningSessionAttemptORM.created_at >= window_start)
                )
            ).scalars().all()
            traces = (
                await uow.session.execute(
                    select(DecisionTraceORM).where(
                        DecisionTraceORM.created_at >= window_start,
                        DecisionTraceORM.trace_type == "session_evaluation",
                    )
                )
            ).scalars().all()
            events = (
                await uow.session.execute(
                    select(EventORM).where(
                        EventORM.created_at >= window_start,
                        EventORM.event_type.in_(
                            [
                                "session_generation_rejected",
                                "session_submission_rejected",
                            ]
                        ),
                    )
                )
            ).scalars().all()
            await uow.commit()

        sessions_started = len(sessions)
        sessions_by_id = {str(item.session_id): item for item in sessions}
        sessions_completed = sum(1 for item in sessions if str(getattr(item, "status", "") or "") == "completed")
        expired_sessions = sum(1 for item in sessions if str(getattr(item, "status", "") or "") == "expired")
        attempt_reference_mismatches = 0
        evaluation_reference_mismatches = 0
        generation_rejections = 0
        stale_contract_rejections = 0
        submission_rejections = 0
        for attempt in attempts:
            session = sessions_by_id.get(str(getattr(attempt, "session_id", "") or ""))
            if session is None or int(getattr(session, "user_id", 0) or 0) != int(getattr(attempt, "user_id", 0) or 0):
                attempt_reference_mismatches += 1
        for trace in traces:
            session = sessions_by_id.get(str(getattr(trace, "reference_id", "") or ""))
            if session is None or int(getattr(session, "user_id", 0) or 0) != int(getattr(trace, "user_id", 0) or 0):
                evaluation_reference_mismatches += 1
        for event in events:
            event_type = str(getattr(event, "event_type", "") or "")
            payload = dict(getattr(event, "payload", {}) or {})
            if event_type == "session_generation_rejected":
                generation_rejections += 1
            if event_type == "session_submission_rejected":
                submission_rejections += 1
                if str(payload.get("reason") or "") == "stale_contract":
                    stale_contract_rejections += 1

        return {
            "sessions_started_7d": sessions_started,
            "sessions_completed_7d": sessions_completed,
            "expired_sessions_7d": expired_sessions,
            "generation_rejections_7d": generation_rejections,
            "submission_rejections_7d": submission_rejections,
            "stale_contract_rejections_7d": stale_contract_rejections,
            "attempt_reference_mismatches_7d": attempt_reference_mismatches,
            "evaluation_reference_mismatches_7d": evaluation_reference_mismatches,
            "session_completion_rate_percent": round((sessions_completed / sessions_started) * 100.0, 2) if sessions_started else 100.0,
            "expired_session_rate_percent": round((expired_sessions / sessions_started) * 100.0, 2) if sessions_started else 0.0,
            "submission_rejection_rate_percent": round((submission_rejections / sessions_started) * 100.0, 2) if sessions_started else 0.0,
        }

    def _evaluate_health(self, metrics: dict[str, Any]):
        sessions_started = int(metrics.get("sessions_started_7d", 0) or 0)
        completion_rate = float(metrics.get("session_completion_rate_percent", 100.0) or 100.0)
        expired_rate = float(metrics.get("expired_session_rate_percent", 0.0) or 0.0)
        stale_contract_rejections = int(metrics.get("stale_contract_rejections_7d", 0) or 0)
        generation_rejections = int(metrics.get("generation_rejections_7d", 0) or 0)
        attempt_reference_mismatches = int(metrics.get("attempt_reference_mismatches_7d", 0) or 0)
        evaluation_reference_mismatches = int(metrics.get("evaluation_reference_mismatches_7d", 0) or 0)

        alerts: list[dict[str, Any]] = []
        if attempt_reference_mismatches > 0 or evaluation_reference_mismatches > 0:
            alerts.append(
                {
                    "code": "session_reference_drift_detected",
                    "severity": "critical",
                    "message": "Session attempts or evaluation traces no longer align with canonical session records.",
                }
            )
        if generation_rejections > 0:
            alerts.append(
                {
                    "code": "session_generation_rejections_detected",
                    "severity": "critical",
                    "message": "Session generation failed quality validation in production traffic.",
                }
            )
        if sessions_started >= 20 and completion_rate < 35.0:
            alerts.append(
                {
                    "code": "session_completion_rate_low",
                    "severity": "critical",
                    "message": "Session completion rate is materially below target.",
                }
            )
        elif sessions_started >= 20 and completion_rate < 55.0:
            alerts.append(
                {
                    "code": "session_completion_rate_low",
                    "severity": "warning",
                    "message": "Session completion rate fell below the expected range.",
                }
            )
        if sessions_started >= 20 and expired_rate > 35.0:
            alerts.append(
                {
                    "code": "session_expiry_rate_high",
                    "severity": "critical",
                    "message": "Too many sessions are expiring before completion.",
                }
            )
        elif sessions_started >= 20 and expired_rate > 20.0:
            alerts.append(
                {
                    "code": "session_expiry_rate_high",
                    "severity": "warning",
                    "message": "Session expiry rate is above the expected range.",
                }
            )
        if stale_contract_rejections >= 5:
            alerts.append(
                {
                    "code": "stale_contract_rejections_high",
                    "severity": "warning",
                    "message": "Clients are submitting against stale session contracts too often.",
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
    ) -> SessionHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.session_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = SessionHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.session_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            SESSION_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "sessions_started_7d",
            "session_completion_rate_percent",
            "expired_session_rate_percent",
            "submission_rejection_rate_percent",
            "stale_contract_rejections_7d",
            "attempt_reference_mismatches_7d",
            "evaluation_reference_mismatches_7d",
        ):
            SESSION_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.session_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            SESSION_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            SESSION_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            SESSION_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "session_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "session_health_transition",
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
            SESSION_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "session_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "session_health_alert",
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

    def _dashboard_drilldowns(
        self,
        *,
        scope_key: str,
        latest_alert_codes: list[str],
        sessions_by_id: dict[str, Any],
        attempts: list[Any],
        traces: list[Any],
    ) -> dict[str, list[dict[str, Any]]]:
        drilldowns: dict[str, list[dict[str, Any]]] = {}
        if scope_key != "global":
            return drilldowns
        if "session_reference_drift_detected" in latest_alert_codes:
            rows: list[dict[str, Any]] = []
            for attempt in attempts:
                session = sessions_by_id.get(str(getattr(attempt, "session_id", "") or ""))
                if session is None or int(getattr(session, "user_id", 0) or 0) != int(getattr(attempt, "user_id", 0) or 0):
                    rows.append(
                        {
                            "artifact_type": "session_attempt",
                            "user_id": int(getattr(attempt, "user_id", 0) or 0),
                            "session_id": str(getattr(attempt, "session_id", "") or ""),
                            "submission_id": str(getattr(attempt, "submission_id", "") or ""),
                        }
                    )
                    if len(rows) >= 5:
                        break
            if len(rows) < 5:
                for trace in traces:
                    session = sessions_by_id.get(str(getattr(trace, "reference_id", "") or ""))
                    if session is None or int(getattr(session, "user_id", 0) or 0) != int(getattr(trace, "user_id", 0) or 0):
                        rows.append(
                            {
                                "artifact_type": "session_evaluation_trace",
                                "user_id": int(getattr(trace, "user_id", 0) or 0),
                                "reference_id": str(getattr(trace, "reference_id", "") or ""),
                                "trace_id": int(getattr(trace, "id", 0) or 0),
                            }
                        )
                        if len(rows) >= 5:
                            break
            if rows:
                drilldowns["session_reference_drift_detected"] = rows
        return drilldowns
