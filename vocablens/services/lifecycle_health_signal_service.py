from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserNotificationStateORM
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    LIFECYCLE_ACTIVE_ALERTS,
    LIFECYCLE_HEALTH_ALERTS,
    LIFECYCLE_HEALTH_RATE,
    LIFECYCLE_HEALTH_SCOPES,
    LIFECYCLE_HEALTH_STATUS,
    LIFECYCLE_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.lifecycle_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")
_STAGE_SCOPES = ("new_user", "activating", "engaged", "at_risk", "churned")


@dataclass(frozen=True)
class LifecycleHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class LifecycleHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork], alert_sink: OpsAlertSink | None = None):
        self._uow_factory = uow_factory
        self._alert_sink = alert_sink or LoggingOpsAlertSink()

    async def evaluate_scope(self, scope_key: str = "global") -> dict[str, Any]:
        metrics = await self._metrics(scope_key)
        status, alerts = self._evaluate_health(scope_key, metrics)
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
            states = await uow.lifecycle_health_states.list_all()
            lifecycle_states = await uow.lifecycle_states.list_all()
            transitions = await uow.lifecycle_transitions.list_all(limit=5000)
            notification_states = (
                await uow.session.execute(select(UserNotificationStateORM))
            ).scalars().all()
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
                    lifecycle_states=lifecycle_states,
                    transitions=transitions,
                    notification_states=notification_states,
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

    async def _metrics(self, scope_key: str) -> dict[str, Any]:
        window_start = utc_now() - timedelta(days=7)
        async with self._uow_factory() as uow:
            lifecycle_states = await uow.lifecycle_states.list_all()
            transitions = await uow.lifecycle_transitions.list_all(limit=5000)
            notification_states = (
                await uow.session.execute(select(UserNotificationStateORM))
            ).scalars().all()
            await uow.commit()

        if scope_key == "global":
            scoped_states = list(lifecycle_states)
            scoped_transitions = [item for item in transitions if getattr(item, "created_at", None) and item.created_at >= window_start]
        else:
            scoped_states = [
                item
                for item in lifecycle_states
                if str(getattr(item, "current_stage", "") or "") == scope_key
            ]
            scoped_transitions = [
                item
                for item in transitions
                if getattr(item, "created_at", None)
                and item.created_at >= window_start
                and str(getattr(item, "to_stage", "") or "") == scope_key
            ]

        total_users = len(scoped_states)
        lifecycle_by_user = {
            int(getattr(item, "user_id", 0) or 0): item
            for item in scoped_states
            if int(getattr(item, "user_id", 0) or 0) > 0
        }
        counts_by_stage: dict[str, int] = {}
        for state in scoped_states:
            stage = str(getattr(state, "current_stage", "") or "")
            counts_by_stage[stage] = counts_by_stage.get(stage, 0) + 1

        if scope_key == "global":
            at_risk_users = counts_by_stage.get("at_risk", 0)
            churned_users = counts_by_stage.get("churned", 0)
        else:
            at_risk_users = counts_by_stage.get("at_risk", 0) if scope_key == "at_risk" else 0
            churned_users = counts_by_stage.get("churned", 0) if scope_key == "churned" else 0

        recovery_notification_suppressed_users = 0
        suppressed_recovery_users = 0
        notification_stage_mismatches = 0
        for item in notification_states:
            stage = str(getattr(item, "lifecycle_stage", "") or "")
            user_id = int(getattr(item, "user_id", 0) or 0)
            lifecycle_state = lifecycle_by_user.get(user_id)
            if lifecycle_state is not None and stage and stage != str(getattr(lifecycle_state, "current_stage", "") or ""):
                notification_stage_mismatches += 1
            if stage not in {"at_risk", "churned"}:
                continue
            if scope_key != "global" and stage != scope_key:
                continue
            policy = dict(getattr(item, "lifecycle_policy", {}) or {})
            if not bool(policy.get("lifecycle_notifications_enabled", True)):
                recovery_notification_suppressed_users += 1
            suppressed_until = getattr(item, "suppressed_until", None)
            if suppressed_until is not None and suppressed_until > utc_now():
                suppressed_recovery_users += 1

        latest_transition_by_user: dict[int, Any] = {}
        for transition in scoped_transitions:
            user_id = int(getattr(transition, "user_id", 0) or 0)
            previous = latest_transition_by_user.get(user_id)
            if previous is None or getattr(transition, "created_at", None) > getattr(previous, "created_at", None):
                latest_transition_by_user[user_id] = transition
        transition_stage_mismatches = 0
        for user_id, transition in latest_transition_by_user.items():
            lifecycle_state = lifecycle_by_user.get(user_id)
            if lifecycle_state is None:
                continue
            if str(getattr(transition, "to_stage", "") or "") != str(getattr(lifecycle_state, "current_stage", "") or ""):
                transition_stage_mismatches += 1

        at_risk_share = round((at_risk_users / total_users) * 100.0, 2) if total_users else 0.0
        churned_share = round((churned_users / total_users) * 100.0, 2) if total_users else 0.0

        return {
            "scope_user_count": total_users,
            "counts_by_stage": dict(sorted(counts_by_stage.items())),
            "at_risk_users": at_risk_users,
            "churned_users": churned_users,
            "at_risk_share_percent": at_risk_share,
            "churned_share_percent": churned_share,
            "recent_transition_count_7d": len(scoped_transitions),
            "recovery_notification_suppressed_users": recovery_notification_suppressed_users,
            "suppressed_recovery_users": suppressed_recovery_users,
            "notification_stage_mismatches": notification_stage_mismatches,
            "transition_stage_mismatches": transition_stage_mismatches,
        }

    def _evaluate_health(self, scope_key: str, metrics: dict[str, Any]):
        total_users = int(metrics.get("scope_user_count", 0) or 0)
        at_risk_share = float(metrics.get("at_risk_share_percent", 0.0) or 0.0)
        churned_share = float(metrics.get("churned_share_percent", 0.0) or 0.0)
        recent_transition_count = int(metrics.get("recent_transition_count_7d", 0) or 0)
        recovery_notification_suppressed_users = int(metrics.get("recovery_notification_suppressed_users", 0) or 0)
        suppressed_recovery_users = int(metrics.get("suppressed_recovery_users", 0) or 0)
        notification_stage_mismatches = int(metrics.get("notification_stage_mismatches", 0) or 0)
        transition_stage_mismatches = int(metrics.get("transition_stage_mismatches", 0) or 0)

        alerts: list[dict[str, Any]] = []
        if notification_stage_mismatches > 0 or transition_stage_mismatches > 0:
            alerts.append(
                {
                    "code": "lifecycle_state_drift_detected",
                    "severity": "critical",
                    "message": "Lifecycle state, transitions, or notification state no longer agree on the user stage.",
                }
            )
        if scope_key == "global":
            if total_users >= 20 and churned_share >= 20.0:
                alerts.append(
                    {
                        "code": "churned_share_high",
                        "severity": "critical",
                        "message": "Churned user share is above the acceptable fleet threshold.",
                    }
                )
            elif total_users >= 20 and at_risk_share >= 35.0:
                alerts.append(
                    {
                        "code": "at_risk_share_high",
                        "severity": "warning",
                        "message": "At-risk user share is above the expected range.",
                    }
                )
            if total_users >= 20 and recent_transition_count == 0:
                alerts.append(
                    {
                        "code": "transition_flow_stalled",
                        "severity": "warning",
                        "message": "No lifecycle transitions were recorded in the last 7 days.",
                    }
                )
            if recovery_notification_suppressed_users > 0 or suppressed_recovery_users > 0:
                alerts.append(
                    {
                        "code": "recovery_messaging_blocked",
                        "severity": "critical",
                        "message": "Recovery lifecycle messaging is blocked for at-risk or churned users.",
                    }
                )
        elif scope_key in {"at_risk", "churned"}:
            if total_users >= 5 and (recovery_notification_suppressed_users > 0 or suppressed_recovery_users > 0):
                alerts.append(
                    {
                        "code": "recovery_messaging_blocked",
                        "severity": "critical",
                        "message": "Recovery lifecycle messaging is blocked inside the recovery stages.",
                    }
                )
            elif total_users >= 5 and recent_transition_count == 0:
                alerts.append(
                    {
                        "code": "recovery_flow_stalled",
                        "severity": "warning",
                        "message": "No new users entered this recovery stage in the last 7 days.",
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
    ) -> LifecycleHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.lifecycle_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = LifecycleHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.lifecycle_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            LIFECYCLE_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "scope_user_count",
            "at_risk_share_percent",
            "churned_share_percent",
            "recent_transition_count_7d",
            "recovery_notification_suppressed_users",
            "suppressed_recovery_users",
            "notification_stage_mismatches",
            "transition_stage_mismatches",
        ):
            LIFECYCLE_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.lifecycle_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            LIFECYCLE_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            LIFECYCLE_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            LIFECYCLE_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "lifecycle_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "lifecycle_health_transition",
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
            LIFECYCLE_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "lifecycle_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "lifecycle_health_alert",
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
        lifecycle_states: list[Any],
        transitions: list[Any],
        notification_states: list[Any],
    ) -> dict[str, list[dict[str, Any]]]:
        drilldowns: dict[str, list[dict[str, Any]]] = {}
        if "lifecycle_state_drift_detected" not in latest_alert_codes:
            return drilldowns
        lifecycle_by_user = {
            int(getattr(item, "user_id", 0) or 0): item
            for item in lifecycle_states
            if int(getattr(item, "user_id", 0) or 0) > 0
        }
        latest_transition_by_user: dict[int, Any] = {}
        for transition in transitions:
            user_id = int(getattr(transition, "user_id", 0) or 0)
            if user_id <= 0:
                continue
            if scope_key != "global" and str(getattr(transition, "to_stage", "") or "") != scope_key:
                continue
            previous = latest_transition_by_user.get(user_id)
            if previous is None or getattr(transition, "created_at", None) > getattr(previous, "created_at", None):
                latest_transition_by_user[user_id] = transition
        rows: list[dict[str, Any]] = []
        for notification_state in notification_states:
            user_id = int(getattr(notification_state, "user_id", 0) or 0)
            lifecycle_state = lifecycle_by_user.get(user_id)
            if lifecycle_state is None:
                continue
            lifecycle_stage = str(getattr(lifecycle_state, "current_stage", "") or "")
            notification_stage = str(getattr(notification_state, "lifecycle_stage", "") or "")
            if scope_key != "global" and lifecycle_stage != scope_key and notification_stage != scope_key:
                continue
            if notification_stage != lifecycle_stage:
                rows.append(
                    {
                        "artifact_type": "notification_state",
                        "user_id": user_id,
                        "lifecycle_stage": lifecycle_stage,
                        "notification_lifecycle_stage": notification_stage,
                        "remediation_endpoint": "/admin/lifecycle/health/remediate",
                        "remediation_request": {
                            "alert_code": "lifecycle_state_drift_detected",
                            "artifact_type": "notification_state",
                            "user_id": user_id,
                        },
                    }
                )
                if len(rows) >= 5:
                    break
        if len(rows) < 5:
            for user_id, transition in latest_transition_by_user.items():
                lifecycle_state = lifecycle_by_user.get(user_id)
                if lifecycle_state is None:
                    continue
                if str(getattr(transition, "to_stage", "") or "") != str(getattr(lifecycle_state, "current_stage", "") or ""):
                    rows.append(
                        {
                            "artifact_type": "lifecycle_transition",
                            "user_id": user_id,
                            "transition_to_stage": str(getattr(transition, "to_stage", "") or ""),
                            "current_stage": str(getattr(lifecycle_state, "current_stage", "") or ""),
                            "reference_id": str(getattr(transition, "reference_id", "") or ""),
                            "remediation_endpoint": "/admin/lifecycle/health/remediate",
                            "remediation_request": {
                                "alert_code": "lifecycle_state_drift_detected",
                                "artifact_type": "lifecycle_transition",
                                "user_id": user_id,
                            },
                        }
                    )
                    if len(rows) >= 5:
                        break
        if rows:
            drilldowns["lifecycle_state_drift_detected"] = rows
        return drilldowns
