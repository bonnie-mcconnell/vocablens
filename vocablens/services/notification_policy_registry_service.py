from __future__ import annotations

from dataclasses import dataclass
import re

from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.notification_policy_service import (
    DEFAULT_NOTIFICATION_POLICY,
    DEFAULT_NOTIFICATION_POLICY_KEY,
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

    def _normalized_policy_payload(self, policy: dict) -> dict:
        merged = dict(DEFAULT_NOTIFICATION_POLICY)
        merged.update({key: value for key, value in dict(policy or {}).items() if key in DEFAULT_NOTIFICATION_POLICY})
        merged["stage_policies"] = {
            stage: dict(values or {})
            for stage, values in dict(merged.get("stage_policies") or {}).items()
        }
        merged["suppression_overrides"] = [dict(item or {}) for item in list(merged.get("suppression_overrides") or [])]
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

    def _normalize_actor(self, changed_by: str | None) -> str:
        actor = (changed_by or "").strip()
        if not actor:
            return "system_admin"
        return actor[:128]

    def _timestamp(self, value) -> str | None:
        return value.isoformat() if getattr(value, "isoformat", None) else None
