from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import (
    EXERCISE_TEMPLATE_ACTIVE_ALERTS,
    EXERCISE_TEMPLATE_HEALTH_ALERTS,
    EXERCISE_TEMPLATE_HEALTH_RATE,
    EXERCISE_TEMPLATE_HEALTH_SCOPES,
    EXERCISE_TEMPLATE_HEALTH_STATUS,
    EXERCISE_TEMPLATE_HEALTH_TRANSITIONS,
)
from vocablens.infrastructure.observability.ops_alerts import LoggingOpsAlertSink, OpsAlertSink
from vocablens.infrastructure.unit_of_work import UnitOfWork


logger = get_logger("vocablens.exercise_template_health")

_HEALTH_STATUSES = ("healthy", "warning", "critical")


@dataclass(frozen=True)
class ExerciseTemplateHealthSnapshot:
    current_status: str | None
    latest_alert_codes: list[str]


class ExerciseTemplateHealthSignalService:
    def __init__(self, uow_factory: type[UnitOfWork], alert_sink: OpsAlertSink | None = None):
        self._uow_factory = uow_factory
        self._alert_sink = alert_sink or LoggingOpsAlertSink()

    async def evaluate_scope(self, scope_key: str = "global") -> dict[str, Any]:
        context = await self._context()
        evaluations = self._evaluate_scopes(context)
        previous = await self._persist_states(evaluations)
        for key, evaluation in evaluations.items():
            self._record_metrics(key, evaluation["health"]["status"], evaluation["health"]["metrics"])
        await self._record_aggregate_metrics()
        for key, evaluation in evaluations.items():
            snapshot = previous.get(key)
            await self._emit_signals(
                scope_key=key,
                previous_status=snapshot.current_status if snapshot else None,
                previous_alert_codes=snapshot.latest_alert_codes if snapshot else [],
                status=evaluation["health"]["status"],
                alerts=evaluation["health"]["alerts"],
                metrics=evaluation["health"]["metrics"],
            )
        return evaluations.get(scope_key, evaluations["global"])

    async def get_health_dashboard(self, *, limit: int = 50) -> dict[str, Any]:
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            states = await uow.exercise_template_health_states.list_all()
            templates = await uow.exercise_templates.list_all()
            latest_audits = {}
            recent_audits: list[Any] = []
            for template in templates:
                template_key = str(template.template_key)
                latest_audits[template_key] = await uow.exercise_template_audits.latest_for_template(template_key)
                recent_audits.extend(await uow.exercise_template_audits.list_by_template(template_key, limit=10))
            await uow.commit()

        if not states:
            await self.evaluate_scope("global")
            async with self._uow_factory() as uow:
                states = await uow.exercise_template_health_states.list_all()
                templates = await uow.exercise_templates.list_all()
                latest_audits = {}
                recent_audits = []
                for template in templates:
                    template_key = str(template.template_key)
                    latest_audits[template_key] = await uow.exercise_template_audits.latest_for_template(template_key)
                    recent_audits.extend(await uow.exercise_template_audits.list_by_template(template_key, limit=10))
                await uow.commit()

        state_by_scope = {str(item.scope_key): item for item in states}
        template_rows: list[dict[str, Any]] = []
        counts_by_status: dict[str, int] = {}
        counts_by_health_status: dict[str, int] = {}
        alert_counts_by_code: dict[str, int] = {}
        latest_audit_at = None
        latest_evaluated_at = None
        recent_audit_count = 0
        window_start = utc_now() - timedelta(days=7)

        for audit in recent_audits:
            created_at = getattr(audit, "created_at", None)
            if created_at is not None and created_at >= window_start:
                recent_audit_count += 1
            latest_audit_at = self._max_timestamp(latest_audit_at, created_at)

        for template in templates:
            template_key = str(template.template_key)
            state = state_by_scope.get(template_key)
            latest_audit = latest_audits.get(template_key)
            fixture_summary = self._fixture_summary(latest_audit)
            metrics = dict(getattr(state, "metrics", {}) or {})
            health_status = str(getattr(state, "current_status", "healthy") or "healthy")
            counts_by_status[str(template.status)] = counts_by_status.get(str(template.status), 0) + 1
            counts_by_health_status[health_status] = counts_by_health_status.get(health_status, 0) + 1
            for code in list(getattr(state, "latest_alert_codes", []) or []):
                alert_counts_by_code[code] = alert_counts_by_code.get(code, 0) + 1
            latest_evaluated_at = self._max_timestamp(latest_evaluated_at, getattr(state, "last_evaluated_at", None))
            template_rows.append(
                {
                    "template_key": template_key,
                    "exercise_type": str(template.exercise_type),
                    "objective": str(template.objective),
                    "difficulty": str(template.difficulty),
                    "status": str(template.status),
                    "runtime_usage_count_7d": int(metrics.get("runtime_usage_count_7d", 0) or 0),
                    "runtime_rejection_count_7d": int(metrics.get("runtime_rejection_count_7d", 0) or 0),
                    "latest_fixture_status": fixture_summary["status"],
                    "latest_failed_fixture_count": int(metrics.get("latest_failed_fixture_count", fixture_summary["failed_fixture_count"]) or 0),
                    "latest_audit_at": self._timestamp(getattr(latest_audit, "created_at", None)),
                    "latest_change_note": str(getattr(latest_audit, "change_note", "") or "") or None,
                    "health_status": health_status,
                    "latest_alert_codes": list(getattr(state, "latest_alert_codes", []) or []),
                    "metrics": metrics,
                    "last_evaluated_at": self._timestamp(getattr(state, "last_evaluated_at", None)),
                }
            )

        template_rows.sort(
            key=lambda item: (
                self._status_rank(item["health_status"]),
                -int(item["latest_failed_fixture_count"]),
                -int(item["runtime_rejection_count_7d"]),
                -int(item["runtime_usage_count_7d"]),
                item["template_key"],
            )
        )
        global_state = state_by_scope.get("global")
        global_metrics = dict(getattr(global_state, "metrics", {}) or {})
        return {
            "summary": {
                "total_templates": len(template_rows),
                "counts_by_status": dict(sorted(counts_by_status.items())),
                "templates_with_failed_fixtures": int(global_metrics.get("templates_with_failed_fixtures", 0) or 0),
                "templates_with_runtime_rejections": int(global_metrics.get("templates_with_runtime_rejections", 0) or 0),
                "recent_audit_count_7d": recent_audit_count,
                "latest_audit_at": self._timestamp(latest_audit_at),
                "counts_by_health_status": dict(sorted(counts_by_health_status.items())),
                "templates_with_alerts": sum(1 for item in template_rows if item["latest_alert_codes"]),
                "alert_counts_by_code": dict(sorted(alert_counts_by_code.items())),
                "latest_evaluated_at": self._timestamp(latest_evaluated_at),
            },
            "attention": [item for item in template_rows if item["health_status"] != "healthy"][:normalized_limit],
            "templates": template_rows[:normalized_limit],
        }

    async def _context(self) -> dict[str, Any]:
        window_start = utc_now() - timedelta(days=7)
        async with self._uow_factory() as uow:
            templates = await uow.exercise_templates.list_all()
            latest_audits = {}
            recent_audits: list[Any] = []
            for template in templates:
                template_key = str(template.template_key)
                latest_audits[template_key] = await uow.exercise_template_audits.latest_for_template(template_key)
                recent_audits.extend(await uow.exercise_template_audits.list_by_template(template_key, limit=10))
            checks = await uow.content_quality_checks.list_since(window_start, limit=5000)
            await uow.commit()
        return {
            "window_start": window_start,
            "templates": templates,
            "latest_audits": latest_audits,
            "recent_audits": recent_audits,
            "checks": checks,
        }

    def _evaluate_scopes(self, context: dict[str, Any]) -> dict[str, Any]:
        usage_by_template: dict[str, int] = {}
        rejection_by_template: dict[str, int] = {}
        for check in list(context.get("checks") or []):
            if str(getattr(check, "artifact_type", "") or "") != "generated_lesson":
                continue
            summary = dict(getattr(check, "artifact_summary", {}) or {})
            template_keys = [
                str(item).strip()
                for item in list(summary.get("template_keys") or [])
                if str(item).strip()
            ]
            for template_key in template_keys:
                usage_by_template[template_key] = usage_by_template.get(template_key, 0) + 1
                if str(getattr(check, "status", "") or "") == "rejected":
                    rejection_by_template[template_key] = rejection_by_template.get(template_key, 0) + 1

        evaluations: dict[str, Any] = {}
        templates_with_failed_fixtures = 0
        templates_with_runtime_rejections = 0
        inactive_template_usage_count = 0
        for template in list(context.get("templates") or []):
            template_key = str(template.template_key)
            usage_count = usage_by_template.get(template_key, 0)
            rejection_count = rejection_by_template.get(template_key, 0)
            fixture_summary = self._fixture_summary(context["latest_audits"].get(template_key))
            if fixture_summary["failed_fixture_count"] > 0:
                templates_with_failed_fixtures += 1
            if rejection_count > 0:
                templates_with_runtime_rejections += 1
            if str(template.status) != "active":
                inactive_template_usage_count += usage_count
            metrics = {
                "runtime_usage_count_7d": usage_count,
                "runtime_rejection_count_7d": rejection_count,
                "runtime_rejection_rate_percent": round((rejection_count / usage_count) * 100.0, 2) if usage_count else 0.0,
                "latest_failed_fixture_count": fixture_summary["failed_fixture_count"],
                "inactive_usage_count_7d": usage_count if str(template.status) != "active" else 0,
            }
            status, alerts = self._evaluate_template_health(template_status=str(template.status), metrics=metrics)
            evaluations[template_key] = {
                "scope_key": template_key,
                "health": {
                    "status": status,
                    "metrics": metrics,
                    "alerts": alerts,
                },
            }

        runtime_usage_count = sum(usage_by_template.values())
        runtime_rejection_count = sum(rejection_by_template.values())
        global_metrics = {
            "total_templates": len(context.get("templates") or []),
            "active_templates": sum(1 for item in context.get("templates") or [] if str(item.status) == "active"),
            "draft_templates": sum(1 for item in context.get("templates") or [] if str(item.status) == "draft"),
            "archived_templates": sum(1 for item in context.get("templates") or [] if str(item.status) == "archived"),
            "templates_with_failed_fixtures": templates_with_failed_fixtures,
            "templates_with_runtime_rejections": templates_with_runtime_rejections,
            "runtime_usage_count_7d": runtime_usage_count,
            "runtime_rejection_count_7d": runtime_rejection_count,
            "runtime_rejection_rate_percent": round((runtime_rejection_count / runtime_usage_count) * 100.0, 2)
            if runtime_usage_count
            else 0.0,
            "inactive_template_usage_count_7d": inactive_template_usage_count,
            "recent_audit_count_7d": sum(
                1
                for item in list(context.get("recent_audits") or [])
                if getattr(item, "created_at", None) is not None and item.created_at >= context["window_start"]
            ),
        }
        global_status, global_alerts = self._evaluate_global_health(global_metrics, evaluations)
        evaluations["global"] = {
            "scope_key": "global",
            "health": {
                "status": global_status,
                "metrics": global_metrics,
                "alerts": global_alerts,
            },
        }
        return evaluations

    def _evaluate_template_health(self, *, template_status: str, metrics: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        usage_count = int(metrics.get("runtime_usage_count_7d", 0) or 0)
        rejection_rate = float(metrics.get("runtime_rejection_rate_percent", 0.0) or 0.0)
        failed_fixture_count = int(metrics.get("latest_failed_fixture_count", 0) or 0)
        alerts: list[dict[str, Any]] = []
        if failed_fixture_count > 0:
            alerts.append(
                {
                    "code": "fixture_regression_detected",
                    "severity": "critical" if template_status == "active" else "warning",
                    "message": "The latest promotion fixture run includes rejected checks for this template.",
                }
            )
        if usage_count >= 5 and rejection_rate >= 20.0:
            alerts.append(
                {
                    "code": "template_runtime_rejection_rate_high",
                    "severity": "critical",
                    "message": "Runtime lesson checks are rejecting this template at an unacceptable rate.",
                }
            )
        elif usage_count >= 3 and rejection_rate >= 10.0:
            alerts.append(
                {
                    "code": "template_runtime_rejection_rate_high",
                    "severity": "warning",
                    "message": "Runtime lesson checks are rejecting this template above the expected range.",
                }
            )
        if template_status != "active" and usage_count > 0:
            alerts.append(
                {
                    "code": "inactive_template_overuse",
                    "severity": "critical" if template_status == "archived" else "warning",
                    "message": "This template is still being used at runtime even though it is not active.",
                }
            )
        return self._status(alerts), alerts

    def _evaluate_global_health(
        self,
        metrics: dict[str, Any],
        evaluations: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        alerts: list[dict[str, Any]] = []
        active_fixture_failures = sum(
            1
            for scope_key, payload in evaluations.items()
            if scope_key != "global"
            and int(payload["health"]["metrics"].get("latest_failed_fixture_count", 0) or 0) > 0
            and any(
                alert.get("code") == "fixture_regression_detected" and alert.get("severity") == "critical"
                for alert in payload["health"]["alerts"]
            )
        )
        critical_inactive_template_usage = sum(
            1
            for scope_key, payload in evaluations.items()
            if scope_key != "global"
            and any(
                alert.get("code") == "inactive_template_overuse" and alert.get("severity") == "critical"
                for alert in payload["health"]["alerts"]
            )
        )
        rejection_rate = float(metrics.get("runtime_rejection_rate_percent", 0.0) or 0.0)
        runtime_usage_count = int(metrics.get("runtime_usage_count_7d", 0) or 0)
        inactive_usage_count = int(metrics.get("inactive_template_usage_count_7d", 0) or 0)
        if active_fixture_failures > 0:
            alerts.append(
                {
                    "code": "fixture_regression_detected",
                    "severity": "critical",
                    "message": "At least one active template has failed its latest promotion fixtures.",
                }
            )
        elif int(metrics.get("templates_with_failed_fixtures", 0) or 0) > 0:
            alerts.append(
                {
                    "code": "fixture_regression_detected",
                    "severity": "warning",
                    "message": "At least one template has failed its latest promotion fixtures.",
                }
            )
        if runtime_usage_count >= 10 and rejection_rate >= 15.0:
            alerts.append(
                {
                    "code": "template_runtime_rejection_rate_high",
                    "severity": "critical",
                    "message": "Template-backed lesson checks are rejecting content at a critical rate.",
                }
            )
        elif runtime_usage_count >= 5 and rejection_rate >= 5.0:
            alerts.append(
                {
                    "code": "template_runtime_rejection_rate_high",
                    "severity": "warning",
                    "message": "Template-backed lesson checks are rejecting content above the expected range.",
                }
            )
        if critical_inactive_template_usage > 0 or inactive_usage_count >= 3:
            alerts.append(
                {
                    "code": "inactive_template_overuse",
                    "severity": "critical",
                    "message": "Inactive templates are still being used heavily at runtime.",
                }
            )
        elif inactive_usage_count > 0:
            alerts.append(
                {
                    "code": "inactive_template_overuse",
                    "severity": "warning",
                    "message": "Inactive templates are still being used at runtime.",
                }
            )
        return self._status(alerts), alerts

    async def _persist_states(
        self,
        evaluations: dict[str, Any],
    ) -> dict[str, ExerciseTemplateHealthSnapshot]:
        previous: dict[str, ExerciseTemplateHealthSnapshot] = {}
        async with self._uow_factory() as uow:
            for scope_key, evaluation in evaluations.items():
                row = await uow.exercise_template_health_states.get(scope_key)
                if row is not None:
                    previous[scope_key] = ExerciseTemplateHealthSnapshot(
                        current_status=str(getattr(row, "current_status", "") or "") or None,
                        latest_alert_codes=list(getattr(row, "latest_alert_codes", []) or []),
                    )
                await uow.exercise_template_health_states.upsert(
                    scope_key=scope_key,
                    current_status=evaluation["health"]["status"],
                    latest_alert_codes=sorted(
                        str(item.get("code") or "") for item in evaluation["health"]["alerts"] if item.get("code")
                    ),
                    metrics=evaluation["health"]["metrics"],
                )
            await uow.commit()
        return previous

    def _record_metrics(self, scope_key: str, status: str, metrics: dict[str, Any]) -> None:
        for candidate in _HEALTH_STATUSES:
            EXERCISE_TEMPLATE_HEALTH_STATUS.labels(scope_key=scope_key, status=candidate).set(
                1 if candidate == status else 0
            )
        for metric_name in (
            "runtime_usage_count_7d",
            "runtime_rejection_count_7d",
            "runtime_rejection_rate_percent",
            "latest_failed_fixture_count",
            "inactive_usage_count_7d",
            "total_templates",
            "active_templates",
            "draft_templates",
            "archived_templates",
            "templates_with_failed_fixtures",
            "templates_with_runtime_rejections",
            "inactive_template_usage_count_7d",
        ):
            if metric_name in metrics:
                EXERCISE_TEMPLATE_HEALTH_RATE.labels(scope_key=scope_key, metric=metric_name).set(
                    float(metrics.get(metric_name, 0.0) or 0.0)
                )

    async def _record_aggregate_metrics(self) -> None:
        async with self._uow_factory() as uow:
            states = await uow.exercise_template_health_states.list_all()
            await uow.commit()
        counts = {candidate: 0 for candidate in _HEALTH_STATUSES}
        for state in states:
            status = str(getattr(state, "current_status", "") or "")
            if status in counts:
                counts[status] += 1
        for candidate in _HEALTH_STATUSES:
            EXERCISE_TEMPLATE_HEALTH_SCOPES.labels(status=candidate).set(float(counts[candidate]))

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
            EXERCISE_TEMPLATE_ACTIVE_ALERTS.labels(scope_key=scope_key, severity=severity).set(float(count))

        if previous_status and previous_status != status:
            EXERCISE_TEMPLATE_HEALTH_TRANSITIONS.labels(
                scope_key=scope_key,
                from_status=previous_status,
                to_status=status,
            ).inc()
            logger.warning(
                "exercise_template_health_transition",
                extra={
                    "scope_key": scope_key,
                    "from_status": previous_status,
                    "to_status": status,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "exercise_template_health_transition",
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
            EXERCISE_TEMPLATE_HEALTH_ALERTS.labels(scope_key=scope_key, code=code, severity=severity).inc()
            logger.warning(
                "exercise_template_health_alert",
                extra={
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": alert,
                    "metrics": metrics,
                },
            )
            await self._alert_sink.emit(
                "exercise_template_health_alert",
                {
                    "scope_key": scope_key,
                    "code": code,
                    "severity": severity,
                    "alert": dict(alert),
                    "metrics": dict(metrics),
                },
            )

    def _fixture_summary(self, audit) -> dict[str, Any]:
        if audit is None:
            return {"status": "unknown", "failed_fixture_count": 0}
        report = dict(getattr(audit, "fixture_report", {}) or {})
        fixtures = [dict(item or {}) for item in list(report.get("fixtures") or [])]
        failed_fixture_count = sum(1 for item in fixtures if str(item.get("status") or "") == "rejected")
        if not fixtures:
            status = "unknown"
        elif failed_fixture_count > 0:
            status = "rejected"
        else:
            status = "passed"
        return {"status": status, "failed_fixture_count": failed_fixture_count}

    def _status(self, alerts: list[dict[str, Any]]) -> str:
        if any(str(item.get("severity") or "") == "critical" for item in alerts):
            return "critical"
        if alerts:
            return "warning"
        return "healthy"

    def _timestamp(self, value) -> str | None:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def _status_rank(self, status: str) -> int:
        order = {"critical": 0, "warning": 1, "healthy": 2}
        return order.get(status, 3)

    def _max_timestamp(self, current, candidate):
        if current is None:
            return candidate
        if candidate is None:
            return current
        return candidate if candidate > current else current
