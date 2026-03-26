from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    MONETIZATION_ACTIVE_ALERTS,
    MONETIZATION_HEALTH_ALERTS,
    MONETIZATION_HEALTH_RATE,
    MONETIZATION_HEALTH_SCOPES,
    MONETIZATION_HEALTH_STATUS,
    MONETIZATION_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.monetization_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class MonetizationHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class MonetizationHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork], alert_sink: OpsAlertSink | None = None):
        self._uow_factory = uow_factory
        self._alert_sink = alert_sink or LoggingOpsAlertSink()

    async def evaluate_scope(self, scope_key: str = "global") -> dict[str, Any]:
        metrics = await self._metrics(scope_key)
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
            states = await uow.monetization_health_states.list_all()
            monetization_states = await uow.monetization_states.list_all()
            lifecycle_states = await uow.lifecycle_states.list_all()
            await uow.commit()
        rows = [
            {
                "scope_key": str(item.scope_key),
                "health_status": str(item.current_status),
                "latest_alert_codes": list(item.latest_alert_codes or []),
                "metrics": dict(item.metrics or {}),
                "alert_drilldowns": self._dashboard_drilldowns(
                    scope_key=str(item.scope_key),
                    latest_alert_codes=list(item.latest_alert_codes or []),
                    monetization_states=monetization_states,
                    lifecycle_states=lifecycle_states,
                ),
                "last_evaluated_at": getattr(item, "last_evaluated_at", None).isoformat() if getattr(item, "last_evaluated_at", None) else None,
            }
            for item in states
        ]
        rows.sort(key=lambda item: (self._status_rank(item["health_status"]), item["scope_key"]))
        counts_by_status = {}
        for row in rows:
            counts_by_status[row["health_status"]] = counts_by_status.get(row["health_status"], 0) + 1
        return {
            "summary": {
                "total_scopes": len(rows),
                "counts_by_health_status": dict(sorted(counts_by_status.items())),
                "scopes_with_alerts": sum(1 for row in rows if row["latest_alert_codes"]),
                "latest_evaluated_at": max((row["last_evaluated_at"] for row in rows if row["last_evaluated_at"]), default=None),
            },
            "attention": [row for row in rows if row["health_status"] != "healthy"][:normalized_limit],
            "scopes": rows[:normalized_limit],
        }

    async def _metrics(self, scope_key: str) -> dict[str, Any]:
        geography = None if scope_key == "global" else scope_key
        async with self._uow_factory() as uow:
            states = await uow.monetization_states.list_all()
            lifecycle_states = await uow.lifecycle_states.list_all()
            events = await uow.monetization_offer_events.list_all(geography=geography)
            await uow.commit()
        filtered_states = [
            state
            for state in states
            if geography is None or str(getattr(state, "current_geography", "") or "") == geography
        ]
        lifecycle_by_user = {
            int(getattr(item, "user_id", 0) or 0): item
            for item in lifecycle_states
            if int(getattr(item, "user_id", 0) or 0) > 0
        }
        tracked_users = len(filtered_states)
        impressions = sum(int(getattr(state, "paywall_impressions", 0) or 0) for state in filtered_states)
        dismissals = sum(int(getattr(state, "paywall_dismissals", 0) or 0) for state in filtered_states)
        acceptances = sum(int(getattr(state, "paywall_acceptances", 0) or 0) for state in filtered_states)
        skips = sum(int(getattr(state, "paywall_skips", 0) or 0) for state in filtered_states)
        lifecycle_stage_mismatches = 0
        for state in filtered_states:
            user_id = int(getattr(state, "user_id", 0) or 0)
            lifecycle_state = lifecycle_by_user.get(user_id)
            if lifecycle_state is None:
                continue
            if str(getattr(state, "lifecycle_stage", "") or "") != str(getattr(lifecycle_state, "current_stage", "") or ""):
                lifecycle_stage_mismatches += 1
        average_fatigue = round(
            sum(float(getattr(state, "fatigue_score", 0) or 0.0) for state in filtered_states) / tracked_users,
            2,
        ) if tracked_users else 0.0
        conversion_rate = round((acceptances / impressions) * 100.0, 2) if impressions else 0.0
        dismissal_rate = round((dismissals / impressions) * 100.0, 2) if impressions else 0.0
        skip_rate = round((skips / impressions) * 100.0, 2) if impressions else 0.0
        last_event_at = None
        if events:
            created_at = getattr(events[0], "created_at", None)
            last_event_at = created_at.isoformat() if created_at and getattr(created_at, "isoformat", None) else None
        return {
            "tracked_users": tracked_users,
            "event_count": len(events),
            "impressions": impressions,
            "dismissals": dismissals,
            "acceptances": acceptances,
            "skips": skips,
            "conversion_rate_percent": conversion_rate,
            "dismissal_rate_percent": dismissal_rate,
            "skip_rate_percent": skip_rate,
            "average_fatigue_score": average_fatigue,
            "lifecycle_stage_mismatches": lifecycle_stage_mismatches,
            "last_event_at": last_event_at,
        }

    def _evaluate_health(self, metrics: dict[str, Any]):
        impressions = int(metrics.get("impressions", 0) or 0)
        tracked_users = int(metrics.get("tracked_users", 0) or 0)
        conversion_rate = float(metrics.get("conversion_rate_percent", 0.0) or 0.0)
        dismissal_rate = float(metrics.get("dismissal_rate_percent", 0.0) or 0.0)
        fatigue = float(metrics.get("average_fatigue_score", 0.0) or 0.0)
        lifecycle_stage_mismatches = int(metrics.get("lifecycle_stage_mismatches", 0) or 0)
        alerts: list[dict[str, Any]] = []
        if lifecycle_stage_mismatches > 0:
            alerts.append(
                {
                    "code": "monetization_lifecycle_stage_mismatch_detected",
                    "severity": "critical",
                    "message": "Monetization state no longer matches canonical lifecycle state for one or more users.",
                }
            )
        if impressions >= 25 and conversion_rate < 3.0:
            alerts.append(
                {
                    "code": "conversion_rate_low",
                    "severity": "critical",
                    "message": "Conversion rate fell below the monetization floor.",
                }
            )
        if impressions >= 25 and dismissal_rate > 55.0:
            alerts.append(
                {
                    "code": "dismissal_rate_high",
                    "severity": "warning",
                    "message": "Paywall dismissal rate is elevated.",
                }
            )
        if tracked_users >= 10 and fatigue > 3.5:
            alerts.append(
                {
                    "code": "fatigue_pressure_high",
                    "severity": "warning",
                    "message": "Average paywall fatigue is above the acceptable range.",
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
    ) -> MonetizationHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.monetization_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = MonetizationHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.monetization_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            MONETIZATION_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "impressions",
            "conversion_rate_percent",
            "dismissal_rate_percent",
            "skip_rate_percent",
            "average_fatigue_score",
            "lifecycle_stage_mismatches",
        ):
            MONETIZATION_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.monetization_health_states.list_all()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            MONETIZATION_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            MONETIZATION_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            MONETIZATION_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "monetization_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "monetization_health_transition",
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
            MONETIZATION_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "monetization_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "monetization_health_alert",
                {
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": dict(alert),
                    "metrics": dict(metrics),
                },
            )

    def _status_rank(self, status: str) -> int:
        ranking = {
            "critical": 0,
            "warning": 1,
            "healthy": 2,
        }
        return ranking.get(status, 3)

    def _dashboard_drilldowns(
        self,
        *,
        scope_key: str,
        latest_alert_codes: list[str],
        monetization_states: list[Any],
        lifecycle_states: list[Any],
    ) -> dict[str, list[dict[str, Any]]]:
        drilldowns: dict[str, list[dict[str, Any]]] = {}
        if "monetization_lifecycle_stage_mismatch_detected" not in latest_alert_codes:
            return drilldowns
        lifecycle_by_user = {
            int(getattr(item, "user_id", 0) or 0): item
            for item in lifecycle_states
            if int(getattr(item, "user_id", 0) or 0) > 0
        }
        rows: list[dict[str, Any]] = []
        for state in monetization_states:
            geography = str(getattr(state, "current_geography", "") or "")
            if scope_key != "global" and geography != scope_key:
                continue
            user_id = int(getattr(state, "user_id", 0) or 0)
            lifecycle_state = lifecycle_by_user.get(user_id)
            if lifecycle_state is None:
                continue
            monetization_stage = str(getattr(state, "lifecycle_stage", "") or "")
            lifecycle_stage = str(getattr(lifecycle_state, "current_stage", "") or "")
            if monetization_stage != lifecycle_stage:
                rows.append(
                    {
                        "artifact_type": "monetization_state",
                        "user_id": user_id,
                        "geography": geography or None,
                        "monetization_lifecycle_stage": monetization_stage,
                        "lifecycle_stage": lifecycle_stage,
                        "remediation_endpoint": "/admin/monetization/health/remediate",
                        "remediation_request": {
                            "alert_code": "monetization_lifecycle_stage_mismatch_detected",
                            "user_id": user_id,
                        },
                    }
                )
                if len(rows) >= 5:
                    break
        if rows:
            drilldowns["monetization_lifecycle_stage_mismatch_detected"] = rows
        return drilldowns
