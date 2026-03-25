from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any

from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.notification_policy_service import (
    DEFAULT_NOTIFICATION_POLICY,
    DEFAULT_NOTIFICATION_POLICY_KEY,
    NotificationPolicyService,
)


_VALID_STATUSES = {"draft", "active", "paused", "archived"}
_POLICY_KEY_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")
_VALID_STAGES = {"new_user", "activating", "engaged", "at_risk", "churned"}


@dataclass(frozen=True)
class NotificationPolicyRegistryUpsert:
    status: str
    is_killed: bool
    description: str | None
    policy: dict
    change_note: str


class NotificationPolicyRegistryService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory
        self._policy_service = NotificationPolicyService(uow_factory)

    async def list_policies(self) -> dict:
        async with self._uow_factory() as uow:
            registries = await uow.notification_policy_registries.list_all()
            latest_audits = {}
            for registry in registries:
                latest_audits[registry.policy_key] = await uow.notification_policy_audits.latest_for_policy(registry.policy_key)
            await uow.commit()
        return {
            "policies": [
                self._summary_payload(item, latest_audits.get(item.policy_key))
                for item in registries
            ]
        }

    async def get_policy(self, policy_key: str) -> dict:
        normalized_key = self._validate_policy_key(policy_key)
        async with self._uow_factory() as uow:
            registry = await uow.notification_policy_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Notification policy '{normalized_key}' not found")
            audits = await uow.notification_policy_audits.list_by_policy(normalized_key, limit=50)
            await uow.commit()
        return {"policy": self._detail_payload(registry, audits)}

    async def upsert_policy(self, *, policy_key: str, command: NotificationPolicyRegistryUpsert, changed_by: str | None) -> dict:
        normalized_key = self._validate_policy_key(policy_key)
        self._validate_command(normalized_key, command)
        actor = self._normalize_actor(changed_by)
        async with self._uow_factory() as uow:
            existing = await uow.notification_policy_registries.get(normalized_key)
            self._validate_transition(existing.status if existing else None, command.status)
            previous_config = self._registry_config(existing) if existing is not None else {}
            saved = await uow.notification_policy_registries.upsert(
                policy_key=normalized_key,
                status=command.status,
                is_killed=command.is_killed,
                description=command.description,
                policy=self._normalized_policy_payload(command.policy),
            )
            audit = await uow.notification_policy_audits.create(
                policy_key=normalized_key,
                action=self._audit_action(existing, command),
                changed_by=actor,
                change_note=command.change_note.strip(),
                previous_config=previous_config,
                new_config=self._registry_config(saved),
            )
            await uow.commit()
        return {"policy": self._detail_payload(saved, [audit])}

    async def list_audit_history(self, policy_key: str, *, limit: int = 50) -> dict:
        normalized_key = self._validate_policy_key(policy_key)
        async with self._uow_factory() as uow:
            registry = await uow.notification_policy_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Notification policy '{normalized_key}' not found")
            audits = await uow.notification_policy_audits.list_by_policy(normalized_key, limit=max(1, min(limit, 200)))
            await uow.commit()
        return {"audit_entries": [self._audit_payload(item) for item in audits]}

    async def get_operator_report(self, policy_key: str, *, limit: int = 50) -> dict:
        normalized_key = self._validate_policy_key(policy_key)
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            registry = await uow.notification_policy_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Notification policy '{normalized_key}' not found")
            audits = await uow.notification_policy_audits.list_by_policy(normalized_key, limit=50)
            deliveries = await uow.notification_deliveries.list_by_policy(normalized_key, limit=normalized_limit)
            suppressions = await uow.notification_suppression_events.list_by_policy(normalized_key, limit=normalized_limit)
            traces = await uow.decision_traces.list_recent(trace_type="notification_selection", limit=max(200, normalized_limit * 4))
            await uow.commit()

        trace_payloads = [
            self._trace_payload(item)
            for item in traces
            if str((item.inputs or {}).get("policy", {}).get("policy_key") or "") == normalized_key
        ][:normalized_limit]
        delivery_payloads = [self._delivery_payload(item) for item in deliveries]
        suppression_payloads = [self._suppression_payload(item) for item in suppressions]

        return {
            "policy": self._detail_payload(registry, audits),
            "latest_decisions": {
                "latest_notification_selection": trace_payloads[0] if trace_payloads else None,
                "latest_delivery": delivery_payloads[0] if delivery_payloads else None,
                "latest_suppression": suppression_payloads[0] if suppression_payloads else None,
                "latest_audit_entry": self._audit_payload(audits[0]) if audits else None,
            },
            "health": self._health_payload(registry, delivery_payloads, suppression_payloads, trace_payloads),
            "delivery_summary": self._delivery_summary_payload(delivery_payloads),
            "suppression_summary": self._suppression_summary_payload(suppression_payloads),
            "trace_summary": self._trace_summary_payload(trace_payloads),
            "version_summary": self._version_summary_payload(
                deliveries=delivery_payloads,
                suppressions=suppression_payloads,
                traces=trace_payloads,
            ),
            "recent_deliveries": delivery_payloads,
            "recent_suppressions": suppression_payloads,
            "recent_traces": trace_payloads,
        }

    def _validate_command(self, policy_key: str, command: NotificationPolicyRegistryUpsert) -> None:
        if command.status not in _VALID_STATUSES:
            raise ValidationError(f"Notification policy '{policy_key}' has invalid status '{command.status}'")
        note = (command.change_note or "").strip()
        if len(note) < 8:
            raise ValidationError("Change note must be at least 8 characters")
        description = (command.description or "").strip()
        if command.description is not None and len(description) > 1000:
            raise ValidationError("Description must be 1000 characters or fewer")
        policy = self._normalized_policy_payload(command.policy)
        cooldown_hours = int(policy.get("cooldown_hours", 0) or 0)
        if cooldown_hours < 1 or cooldown_hours > 168:
            raise ValidationError(f"Notification policy '{policy_key}' cooldown_hours must be between 1 and 168")
        frequency_limit = int(policy.get("default_frequency_limit", 0) or 0)
        if frequency_limit < 0 or frequency_limit > 24:
            raise ValidationError(f"Notification policy '{policy_key}' default_frequency_limit must be between 0 and 24")
        preferred_hour = int(policy.get("default_preferred_time_of_day", 0) or 0)
        if preferred_hour < 0 or preferred_hour > 23:
            raise ValidationError(f"Notification policy '{policy_key}' default_preferred_time_of_day must be between 0 and 23")
        self._validate_governance(policy_key, dict(policy.get("governance") or {}))
        self._validate_stage_policies(policy_key, dict(policy.get("stage_policies") or {}))
        self._validate_overrides(policy_key, list(policy.get("suppression_overrides") or []))

    def _validate_policy_key(self, policy_key: str) -> str:
        normalized_key = (policy_key or "").strip()
        if not _POLICY_KEY_PATTERN.match(normalized_key):
            raise ValidationError("Notification policy key must match ^[a-z0-9_]{3,64}$")
        return normalized_key

    def _validate_transition(self, current_status: str | None, next_status: str) -> None:
        if current_status is None:
            return
        allowed = {
            "draft": {"draft", "active", "paused", "archived"},
            "active": {"active", "paused", "archived"},
            "paused": {"paused", "active", "archived"},
            "archived": {"archived"},
        }
        if next_status not in allowed.get(current_status, {current_status}):
            raise ValidationError(f"Notification policy status cannot move from '{current_status}' to '{next_status}'")

    def _validate_stage_policies(self, policy_key: str, stage_policies: dict[str, dict]) -> None:
        if set(stage_policies) != _VALID_STAGES:
            raise ValidationError(f"Notification policy '{policy_key}' must define all lifecycle stages exactly once")
        for stage, payload in stage_policies.items():
            values = dict(payload or {})
            recovery_window_hours = int(values.get("recovery_window_hours", 0) or 0)
            if recovery_window_hours < 0 or recovery_window_hours > 168:
                raise ValidationError(f"Notification policy '{policy_key}' stage '{stage}' recovery_window_hours must be between 0 and 168")

    def _validate_overrides(self, policy_key: str, overrides: list[dict]) -> None:
        seen: set[tuple[str, str]] = set()
        for item in overrides:
            payload = dict(item or {})
            source_context = str(payload.get("source_context") or "").strip()
            stage = str(payload.get("stage") or "").strip()
            if not source_context:
                raise ValidationError(f"Notification policy '{policy_key}' override is missing source_context")
            if stage not in _VALID_STAGES:
                raise ValidationError(f"Notification policy '{policy_key}' override has invalid stage '{stage}'")
            signature = (source_context, stage)
            if signature in seen:
                raise ValidationError(f"Notification policy '{policy_key}' contains duplicate override for source_context '{source_context}' and stage '{stage}'")
            seen.add(signature)

    def _validate_governance(self, policy_key: str, governance: dict[str, Any]) -> None:
        payload = dict(DEFAULT_NOTIFICATION_POLICY.get("governance") or {})
        payload.update(dict(governance or {}))
        min_sample_size = int(payload.get("min_sample_size", 25) or 0)
        if min_sample_size < 1 or min_sample_size > 100000:
            raise ValidationError(f"Notification policy '{policy_key}' governance min_sample_size must be between 1 and 100000")
        for field_name in (
            "max_failed_delivery_rate_percent",
            "max_suppression_rate_percent",
            "max_send_rate_drop_percent",
        ):
            value = float(payload.get(field_name, 0.0) or 0.0)
            if value < 0.0 or value > 100.0:
                raise ValidationError(f"Notification policy '{policy_key}' governance {field_name} must be between 0 and 100")

    def _normalized_policy_payload(self, policy: dict) -> dict:
        merged = dict(DEFAULT_NOTIFICATION_POLICY)
        merged.update({key: value for key, value in dict(policy or {}).items() if key in DEFAULT_NOTIFICATION_POLICY})
        merged["stage_policies"] = {
            stage: dict(values or {})
            for stage, values in dict(merged.get("stage_policies") or {}).items()
        }
        merged["suppression_overrides"] = [dict(item or {}) for item in list(merged.get("suppression_overrides") or [])]
        governance = dict(DEFAULT_NOTIFICATION_POLICY.get("governance") or {})
        governance.update(dict(merged.get("governance") or {}))
        merged["governance"] = governance
        return merged

    def _registry_config(self, registry) -> dict:
        if registry is None:
            return {}
        return {
            "policy_key": str(registry.policy_key),
            "status": str(registry.status),
            "is_killed": bool(registry.is_killed),
            "description": registry.description,
            "policy": dict(registry.policy or {}),
            "created_at": self._timestamp(getattr(registry, "created_at", None)),
            "updated_at": self._timestamp(getattr(registry, "updated_at", None)),
        }

    def _summary_payload(self, registry, latest_audit) -> dict:
        return {
            **self._registry_config(registry),
            "latest_change": self._audit_payload(latest_audit) if latest_audit is not None else None,
        }

    def _detail_payload(self, registry, audits: list) -> dict:
        return {
            **self._registry_config(registry),
            "audit_entries": [self._audit_payload(item) for item in audits],
        }

    def _audit_action(self, existing, command: NotificationPolicyRegistryUpsert) -> str:
        if existing is None:
            return "created"
        if not bool(existing.is_killed) and command.is_killed:
            return "kill_switch_enabled"
        if bool(existing.is_killed) and not command.is_killed:
            return "kill_switch_disabled"
        if str(existing.status) != command.status:
            return f"status_{command.status}"
        return "updated"

    def _audit_payload(self, audit) -> dict:
        return {
            "id": int(audit.id),
            "policy_key": str(audit.policy_key),
            "action": str(audit.action),
            "changed_by": str(audit.changed_by),
            "change_note": str(audit.change_note),
            "previous_config": dict(audit.previous_config or {}),
            "new_config": dict(audit.new_config or {}),
            "created_at": self._timestamp(getattr(audit, "created_at", None)),
        }

    def _delivery_payload(self, row) -> dict:
        return {
            "id": int(row.id),
            "user_id": int(row.user_id),
            "category": str(row.category),
            "provider": str(row.provider),
            "status": str(row.status),
            "policy_key": row.policy_key,
            "policy_version": row.policy_version,
            "source_context": row.source_context,
            "reference_id": row.reference_id,
            "title": str(row.title),
            "body": str(row.body),
            "error_message": row.error_message,
            "attempt_count": int(row.attempt_count or 0),
            "created_at": self._timestamp(getattr(row, "created_at", None)),
            "updated_at": self._timestamp(getattr(row, "updated_at", None)),
        }

    def _suppression_payload(self, row) -> dict:
        return {
            "id": int(row.id),
            "user_id": int(row.user_id),
            "event_type": str(row.event_type),
            "source": str(row.source),
            "reference_id": row.reference_id,
            "policy_key": row.policy_key,
            "policy_version": row.policy_version,
            "lifecycle_stage": row.lifecycle_stage,
            "suppression_reason": row.suppression_reason,
            "suppressed_until": self._timestamp(getattr(row, "suppressed_until", None)),
            "payload": dict(row.payload or {}),
            "created_at": self._timestamp(getattr(row, "created_at", None)),
        }

    def _trace_payload(self, trace) -> dict:
        return {
            "id": int(trace.id),
            "user_id": int(trace.user_id),
            "trace_type": str(trace.trace_type),
            "source": str(trace.source),
            "reference_id": trace.reference_id,
            "policy_version": str(trace.policy_version),
            "inputs": dict(trace.inputs or {}),
            "outputs": dict(trace.outputs or {}),
            "reason": trace.reason,
            "created_at": self._timestamp(getattr(trace, "created_at", None)),
        }

    def _delivery_summary_payload(self, deliveries: list[dict[str, Any]]) -> dict:
        status_counts = Counter(str(item.get("status") or "") for item in deliveries)
        provider_counts = Counter(str(item.get("provider") or "") for item in deliveries)
        category_counts = Counter(str(item.get("category") or "") for item in deliveries)
        unique_users = {int(item["user_id"]) for item in deliveries}
        return {
            "total_deliveries": len(deliveries),
            "affected_users": len(unique_users),
            "counts_by_status": dict(sorted(status_counts.items())),
            "counts_by_provider": dict(sorted(provider_counts.items())),
            "counts_by_category": dict(sorted(category_counts.items())),
            "latest_delivery_at": self._latest_timestamp(deliveries),
        }

    def _suppression_summary_payload(self, suppressions: list[dict[str, Any]]) -> dict:
        event_counts = Counter(str(item.get("event_type") or "") for item in suppressions)
        stage_counts = Counter(str(item.get("lifecycle_stage") or "") for item in suppressions)
        unique_users = {int(item["user_id"]) for item in suppressions}
        return {
            "total_suppressions": len(suppressions),
            "affected_users": len(unique_users),
            "counts_by_type": dict(sorted(event_counts.items())),
            "counts_by_stage": dict(sorted(stage_counts.items())),
            "latest_suppression_at": self._latest_timestamp(suppressions),
        }

    def _trace_summary_payload(self, traces: list[dict[str, Any]]) -> dict:
        reason_counts = Counter(str(item.get("reason") or "") for item in traces if item.get("reason"))
        return {
            "total_traces": len(traces),
            "counts_by_reason": dict(sorted(reason_counts.items())),
            "latest_trace_at": self._latest_timestamp(traces),
        }

    def _version_summary_payload(
        self,
        *,
        deliveries: list[dict[str, Any]],
        suppressions: list[dict[str, Any]],
        traces: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        versions: dict[str, dict[str, Any]] = {}
        for item in deliveries:
            version = str(item.get("policy_version") or "unknown")
            payload = versions.setdefault(
                version,
                {
                    "policy_version": version,
                    "delivery_count": 0,
                    "suppression_count": 0,
                    "trace_count": 0,
                    "delivery_statuses": Counter(),
                    "suppression_types": Counter(),
                    "latest_activity_at": None,
                },
            )
            payload["delivery_count"] += 1
            payload["delivery_statuses"][str(item.get("status") or "")] += 1
            payload["latest_activity_at"] = self._max_timestamp(
                payload["latest_activity_at"],
                item.get("created_at"),
            )
        for item in suppressions:
            version = str(item.get("policy_version") or "unknown")
            payload = versions.setdefault(
                version,
                {
                    "policy_version": version,
                    "delivery_count": 0,
                    "suppression_count": 0,
                    "trace_count": 0,
                    "delivery_statuses": Counter(),
                    "suppression_types": Counter(),
                    "latest_activity_at": None,
                },
            )
            payload["suppression_count"] += 1
            payload["suppression_types"][str(item.get("event_type") or "")] += 1
            payload["latest_activity_at"] = self._max_timestamp(
                payload["latest_activity_at"],
                item.get("created_at"),
            )
        for item in traces:
            version = str(item.get("policy_version") or "unknown")
            payload = versions.setdefault(
                version,
                {
                    "policy_version": version,
                    "delivery_count": 0,
                    "suppression_count": 0,
                    "trace_count": 0,
                    "delivery_statuses": Counter(),
                    "suppression_types": Counter(),
                    "latest_activity_at": None,
                },
            )
            payload["trace_count"] += 1
            payload["latest_activity_at"] = self._max_timestamp(
                payload["latest_activity_at"],
                item.get("created_at"),
            )
        return [
            {
                "policy_version": item["policy_version"],
                "delivery_count": int(item["delivery_count"]),
                "suppression_count": int(item["suppression_count"]),
                "trace_count": int(item["trace_count"]),
                "delivery_statuses": dict(sorted(item["delivery_statuses"].items())),
                "suppression_types": dict(sorted(item["suppression_types"].items())),
                "latest_activity_at": item["latest_activity_at"],
            }
            for item in sorted(
                versions.values(),
                key=lambda value: (value["latest_activity_at"] or "", value["policy_version"]),
                reverse=True,
            )
        ]

    def _latest_timestamp(self, items: list[dict[str, Any]]) -> str | None:
        return max((item.get("created_at") for item in items if item.get("created_at")), default=None)

    def _max_timestamp(self, left: str | None, right: str | None) -> str | None:
        if left is None:
            return right
        if right is None:
            return left
        return max(left, right)

    def _health_payload(
        self,
        registry,
        deliveries: list[dict[str, Any]],
        suppressions: list[dict[str, Any]],
        traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        runtime_policy = self._policy_service._policy_from_config(
            str(registry.policy_key),
            dict(registry.policy or {}),
        )
        governance = runtime_policy.governance
        sent_count = sum(1 for item in deliveries if str(item.get("status") or "") == "sent")
        failed_count = sum(1 for item in deliveries if str(item.get("status") or "") == "failed")
        delivery_count = len(deliveries)
        suppression_count = len(suppressions)
        total_outcomes = delivery_count + suppression_count
        failed_rate = self._percent(failed_count, delivery_count)
        suppression_rate = self._percent(suppression_count, total_outcomes)
        version_summary = self._version_summary_payload(
            deliveries=deliveries,
            suppressions=suppressions,
            traces=traces,
        )
        alerts: list[dict[str, Any]] = []

        if delivery_count >= governance.min_sample_size and failed_rate > governance.max_failed_delivery_rate_percent:
            alerts.append(
                {
                    "code": "failed_delivery_rate_high",
                    "severity": "critical",
                    "message": "Failed delivery rate is above the configured threshold.",
                    "observed_percent": failed_rate,
                    "threshold_percent": governance.max_failed_delivery_rate_percent,
                }
            )
        if total_outcomes >= governance.min_sample_size and suppression_rate > governance.max_suppression_rate_percent:
            alerts.append(
                {
                    "code": "suppression_rate_high",
                    "severity": "warning",
                    "message": "Suppression rate is above the configured threshold.",
                    "observed_percent": suppression_rate,
                    "threshold_percent": governance.max_suppression_rate_percent,
                }
            )
        if len(version_summary) >= 2:
            current = version_summary[0]
            previous = version_summary[1]
            current_sample = int(current.get("delivery_count", 0) or 0)
            previous_sample = int(previous.get("delivery_count", 0) or 0)
            if current_sample >= governance.min_sample_size and previous_sample >= governance.min_sample_size:
                current_send_rate = self._percent(
                    int(current.get("delivery_statuses", {}).get("sent", 0) or 0),
                    current_sample,
                )
                previous_send_rate = self._percent(
                    int(previous.get("delivery_statuses", {}).get("sent", 0) or 0),
                    previous_sample,
                )
                send_rate_drop = max(0.0, previous_send_rate - current_send_rate)
                if send_rate_drop > governance.max_send_rate_drop_percent:
                    alerts.append(
                        {
                            "code": "send_rate_regression",
                            "severity": "critical",
                            "message": "Current policy version send rate regressed beyond the configured threshold.",
                            "observed_percent": send_rate_drop,
                            "threshold_percent": governance.max_send_rate_drop_percent,
                            "current_policy_version": current.get("policy_version"),
                            "previous_policy_version": previous.get("policy_version"),
                        }
                    )

        status = "healthy"
        if any(item["severity"] == "critical" for item in alerts):
            status = "critical"
        elif alerts:
            status = "warning"

        return {
            "status": status,
            "evaluated_window_size": max(delivery_count, suppression_count, len(traces)),
            "governance": {
                "min_sample_size": governance.min_sample_size,
                "max_failed_delivery_rate_percent": governance.max_failed_delivery_rate_percent,
                "max_suppression_rate_percent": governance.max_suppression_rate_percent,
                "max_send_rate_drop_percent": governance.max_send_rate_drop_percent,
            },
            "metrics": {
                "delivery_count": delivery_count,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "suppression_count": suppression_count,
                "failed_delivery_rate_percent": failed_rate,
                "suppression_rate_percent": suppression_rate,
            },
            "alerts": alerts,
        }

    def _percent(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((float(numerator) / float(denominator)) * 100.0, 2)

    def _normalize_actor(self, changed_by: str | None) -> str:
        actor = (changed_by or "").strip()
        if not actor:
            return "system_admin"
        return actor[:128]

    def _timestamp(self, value) -> str | None:
        return value.isoformat() if getattr(value, "isoformat", None) else None
