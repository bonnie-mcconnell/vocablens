from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    DAILY_LOOP_ACTIVE_ALERTS,
    DAILY_LOOP_HEALTH_ALERTS,
    DAILY_LOOP_HEALTH_RATE,
    DAILY_LOOP_HEALTH_SCOPES,
    DAILY_LOOP_HEALTH_STATUS,
    DAILY_LOOP_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.daily_loop_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class DailyLoopHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class DailyLoopHealthSignalService:
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
            states = await uow.daily_loop_health_states.list_all()
            missions = await uow.daily_missions.list_all(limit=5000)
            reward_chests = await uow.reward_chests.list_all(limit=5000)
            await uow.commit()
        rows = [
            {
                "scope_key": str(item.scope_key),
                "health_status": str(item.current_status),
                "latest_alert_codes": list(item.latest_alert_codes or []),
                "metrics": dict(item.metrics or {}),
                "alert_drilldowns": self._dashboard_drilldowns(
                    latest_alert_codes=list(item.latest_alert_codes or []),
                    missions=missions,
                    reward_chests=reward_chests,
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
        now = utc_now()
        today = now.date().isoformat()
        window_start = now - timedelta(days=7)
        async with self._uow_factory() as uow:
            engagement_states = await uow.engagement_states.list_all()
            missions = await uow.daily_missions.list_all(limit=5000)
            reward_chests = await uow.reward_chests.list_all(limit=5000)
            await uow.commit()

        recent_missions = [
            item
            for item in missions
            if getattr(item, "created_at", None) and item.created_at >= window_start
        ]
        active_users = {
            int(item.user_id)
            for item in engagement_states
            if int(getattr(item, "sessions_last_3_days", 0) or 0) > 0
        }
        today_missions = [item for item in missions if str(getattr(item, "mission_date", "") or "") == today]
        today_mission_users = {int(item.user_id) for item in today_missions}
        completed_missions = [
            item
            for item in recent_missions
            if str(getattr(item, "status", "") or "") == "completed"
        ]
        missions_by_id = {
            int(getattr(item, "id", 0) or 0): item
            for item in missions
            if int(getattr(item, "id", 0) or 0) > 0
        }
        unlocked_chests = [
            item
            for item in reward_chests
            if getattr(item, "unlocked_at", None) and item.unlocked_at >= window_start
        ]
        reward_mission_mismatches = 0
        for chest in reward_chests:
            mission = missions_by_id.get(int(getattr(chest, "mission_id", 0) or 0))
            if mission is None or int(getattr(mission, "user_id", 0) or 0) != int(getattr(chest, "user_id", 0) or 0):
                reward_mission_mismatches += 1
        shield_violation_users = sum(
            1 for item in engagement_states if int(getattr(item, "shields_used_this_week", 0) or 0) > 1
        )
        mission_issue_coverage = round((len(today_mission_users) / len(active_users)) * 100.0, 2) if active_users else 100.0
        mission_completion_rate = round((len(completed_missions) / len(recent_missions)) * 100.0, 2) if recent_missions else 100.0

        return {
            "active_users_last_3_days": len(active_users),
            "today_missions_issued": len(today_missions),
            "today_mission_users": len(today_mission_users),
            "issued_missions_7d": len(recent_missions),
            "completed_missions_7d": len(completed_missions),
            "reward_chests_unlocked_7d": len(unlocked_chests),
            "mission_issue_coverage_percent": mission_issue_coverage,
            "mission_completion_rate_percent": mission_completion_rate,
            "reward_unlock_gap": max(0, len(completed_missions) - len(unlocked_chests)),
            "reward_mission_mismatches": reward_mission_mismatches,
            "shield_violation_users": shield_violation_users,
        }

    def _evaluate_health(self, metrics: dict[str, Any]):
        active_users = int(metrics.get("active_users_last_3_days", 0) or 0)
        issued_missions = int(metrics.get("issued_missions_7d", 0) or 0)
        mission_issue_coverage = float(metrics.get("mission_issue_coverage_percent", 100.0) or 100.0)
        mission_completion_rate = float(metrics.get("mission_completion_rate_percent", 100.0) or 100.0)
        reward_unlock_gap = int(metrics.get("reward_unlock_gap", 0) or 0)
        reward_mission_mismatches = int(metrics.get("reward_mission_mismatches", 0) or 0)
        shield_violation_users = int(metrics.get("shield_violation_users", 0) or 0)

        alerts: list[dict[str, Any]] = []
        if reward_mission_mismatches > 0:
            alerts.append(
                {
                    "code": "reward_mission_reference_mismatch_detected",
                    "severity": "critical",
                    "message": "Reward chests no longer line up with canonical mission ownership.",
                }
            )
        if active_users >= 10 and mission_issue_coverage < 75.0:
            alerts.append(
                {
                    "code": "mission_issue_coverage_low",
                    "severity": "critical",
                    "message": "Too many active users are missing a daily mission today.",
                }
            )
        elif active_users >= 10 and mission_issue_coverage < 90.0:
            alerts.append(
                {
                    "code": "mission_issue_coverage_low",
                    "severity": "warning",
                    "message": "Daily mission coverage dropped below the target range.",
                }
            )
        if issued_missions >= 20 and mission_completion_rate < 35.0:
            alerts.append(
                {
                    "code": "mission_completion_rate_low",
                    "severity": "critical",
                    "message": "Daily mission completion rate is materially below target.",
                }
            )
        elif issued_missions >= 20 and mission_completion_rate < 55.0:
            alerts.append(
                {
                    "code": "mission_completion_rate_low",
                    "severity": "warning",
                    "message": "Daily mission completion rate is below the expected range.",
                }
            )
        if reward_unlock_gap >= 3:
            alerts.append(
                {
                    "code": "reward_unlock_gap_high",
                    "severity": "critical",
                    "message": "Completed missions and unlocked reward chests have drifted apart.",
                }
            )
        if shield_violation_users > 0:
            alerts.append(
                {
                    "code": "skip_shield_violation",
                    "severity": "critical",
                    "message": "At least one user exceeded the weekly skip shield limit.",
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
    ) -> DailyLoopHealthSnapshot | None:
        async with self._uow_factory() as uow:
            previous_row = await uow.daily_loop_health_states.get(scope_key)
            previous = None
            if previous_row is not None:
                previous = DailyLoopHealthSnapshot(
                    current_status=str(getattr(previous_row, "current_status", "") or "") or None,
                    latest_alert_codes=list(getattr(previous_row, "latest_alert_codes", []) or []),
                )
            await uow.daily_loop_health_states.upsert(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=latest_alert_codes,
                metrics=metrics,
            )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            DAILY_LOOP_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "active_users_last_3_days",
            "today_mission_users",
            "mission_issue_coverage_percent",
            "mission_completion_rate_percent",
            "reward_unlock_gap",
            "reward_mission_mismatches",
            "shield_violation_users",
        ):
            DAILY_LOOP_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                float(metrics.get(metric_name, 0.0) or 0.0)
            )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.daily_loop_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            DAILY_LOOP_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            DAILY_LOOP_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            DAILY_LOOP_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "daily_loop_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "daily_loop_health_transition",
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
            DAILY_LOOP_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "daily_loop_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "daily_loop_health_alert",
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
        latest_alert_codes: list[str],
        missions: list[Any],
        reward_chests: list[Any],
    ) -> dict[str, list[dict[str, Any]]]:
        drilldowns: dict[str, list[dict[str, Any]]] = {}
        if "reward_mission_reference_mismatch_detected" not in latest_alert_codes:
            return drilldowns
        missions_by_id = {
            int(getattr(item, "id", 0) or 0): item
            for item in missions
            if int(getattr(item, "id", 0) or 0) > 0
        }
        rows: list[dict[str, Any]] = []
        for chest in reward_chests:
            mission = missions_by_id.get(int(getattr(chest, "mission_id", 0) or 0))
            if mission is None or int(getattr(mission, "user_id", 0) or 0) != int(getattr(chest, "user_id", 0) or 0):
                rows.append(
                    {
                        "artifact_type": "reward_chest",
                        "user_id": int(getattr(chest, "user_id", 0) or 0),
                        "mission_id": int(getattr(chest, "mission_id", 0) or 0),
                        "reward_chest_id": int(getattr(chest, "id", 0) or 0),
                        "mission_owner_user_id": int(getattr(mission, "user_id", 0) or 0) if mission is not None else None,
                        "remediation_endpoint": "/admin/daily-loop/health/remediate",
                        "remediation_request": {
                            "alert_code": "reward_mission_reference_mismatch_detected",
                            "reward_chest_id": int(getattr(chest, "id", 0) or 0),
                            "mission_id": int(getattr(chest, "mission_id", 0) or 0),
                        },
                    }
                )
                if len(rows) >= 5:
                    break
        if rows:
            drilldowns["reward_mission_reference_mismatch_detected"] = rows
        return drilldowns
