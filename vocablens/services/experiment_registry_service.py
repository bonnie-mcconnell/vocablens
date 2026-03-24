from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re

from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.infrastructure.unit_of_work import UnitOfWork


_VALID_STATUSES = {"draft", "active", "paused", "archived"}
_EXPERIMENT_KEY_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")


@dataclass(frozen=True)
class ExperimentRegistryVariantInput:
    name: str
    weight: int


@dataclass(frozen=True)
class ExperimentRegistryUpsert:
    status: str
    rollout_percentage: int
    is_killed: bool
    description: str | None
    variants: tuple[ExperimentRegistryVariantInput, ...]
    change_note: str


class ExperimentRegistryService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def list_registries(self) -> dict:
        async with self._uow_factory() as uow:
            registries = await uow.experiment_registries.list_all()
            assignments = await uow.experiment_assignments.list_all()
            exposures = await uow.experiment_exposures.list_all()
            audits_by_key = {}
            for registry in registries:
                latest = await uow.experiment_registry_audits.latest_for_experiment(registry.experiment_key)
                audits_by_key[registry.experiment_key] = latest
            await uow.commit()

        assignment_counts = self._variant_counts(assignments)
        exposure_counts = self._variant_counts(exposures)
        experiments = []
        for registry in registries:
            experiments.append(
                self._registry_summary_payload(
                    registry=registry,
                    assignment_counts=assignment_counts.get(registry.experiment_key, Counter()),
                    exposure_counts=exposure_counts.get(registry.experiment_key, Counter()),
                    latest_audit=audits_by_key.get(registry.experiment_key),
                )
            )
        return {"experiments": experiments}

    async def get_registry(self, experiment_key: str) -> dict:
        async with self._uow_factory() as uow:
            registry = await uow.experiment_registries.get(experiment_key)
            if registry is None:
                raise NotFoundError(f"Experiment '{experiment_key}' not found")
            assignments = await uow.experiment_assignments.list_all(experiment_key)
            exposures = await uow.experiment_exposures.list_all(experiment_key)
            audits = await uow.experiment_registry_audits.list_by_experiment(experiment_key, limit=50)
            await uow.commit()

        assignment_counts = self._variant_counts(assignments).get(experiment_key, Counter())
        exposure_counts = self._variant_counts(exposures).get(experiment_key, Counter())
        return {
            "experiment": self._registry_detail_payload(
                registry=registry,
                assignment_counts=assignment_counts,
                exposure_counts=exposure_counts,
                audits=audits,
            )
        }

    async def upsert_registry(
        self,
        *,
        experiment_key: str,
        command: ExperimentRegistryUpsert,
        changed_by: str,
    ) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        self._validate_command(normalized_key, command)
        actor = self._normalize_actor(changed_by)

        async with self._uow_factory() as uow:
            existing = await uow.experiment_registries.get(normalized_key)
            self._validate_transition(existing.status if existing else None, command.status)
            previous_config = self._registry_config(existing) if existing is not None else {}
            saved = await uow.experiment_registries.upsert(
                experiment_key=normalized_key,
                status=command.status,
                rollout_percentage=command.rollout_percentage,
                is_killed=command.is_killed,
                description=command.description,
                variants=[self._variant_payload(item) for item in command.variants],
            )
            audit = await uow.experiment_registry_audits.create(
                experiment_key=normalized_key,
                action=self._audit_action(existing, command),
                changed_by=actor,
                change_note=command.change_note.strip(),
                previous_config=previous_config,
                new_config=self._registry_config(saved),
            )
            assignments = await uow.experiment_assignments.list_all(normalized_key)
            exposures = await uow.experiment_exposures.list_all(normalized_key)
            audits = [audit]
            await uow.commit()

        assignment_counts = self._variant_counts(assignments).get(normalized_key, Counter())
        exposure_counts = self._variant_counts(exposures).get(normalized_key, Counter())
        return {
            "experiment": self._registry_detail_payload(
                registry=saved,
                assignment_counts=assignment_counts,
                exposure_counts=exposure_counts,
                audits=audits,
            )
        }

    async def list_audit_history(self, experiment_key: str, *, limit: int = 50) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        async with self._uow_factory() as uow:
            registry = await uow.experiment_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Experiment '{normalized_key}' not found")
            audits = await uow.experiment_registry_audits.list_by_experiment(normalized_key, limit=max(1, min(limit, 200)))
            await uow.commit()
        return {"audit_entries": [self._audit_payload(item) for item in audits]}

    def _validate_command(self, experiment_key: str, command: ExperimentRegistryUpsert) -> None:
        if command.status not in _VALID_STATUSES:
            raise ValidationError(f"Experiment '{experiment_key}' has invalid status '{command.status}'")
        if command.rollout_percentage < 0 or command.rollout_percentage > 100:
            raise ValidationError(f"Experiment '{experiment_key}' rollout percentage must be between 0 and 100")
        note = (command.change_note or "").strip()
        if len(note) < 8:
            raise ValidationError("Change note must be at least 8 characters")
        description = (command.description or "").strip()
        if command.description is not None and len(description) > 1000:
            raise ValidationError("Description must be 1000 characters or fewer")
        if command.status == "active" and not command.is_killed and command.rollout_percentage == 0:
            raise ValidationError("Active experiments must have rollout percentage greater than 0 unless killed")
        variants = command.variants
        if not variants:
            raise ValidationError(f"Experiment '{experiment_key}' must declare at least one variant")
        seen_names: set[str] = set()
        total_weight = 0
        has_control = False
        for variant in variants:
            name = (variant.name or "").strip()
            if not name:
                raise ValidationError(f"Experiment '{experiment_key}' contains an empty variant name")
            if len(name) > 64:
                raise ValidationError(f"Experiment '{experiment_key}' variant '{name}' exceeds 64 characters")
            if name in seen_names:
                raise ValidationError(f"Experiment '{experiment_key}' contains duplicate variant '{name}'")
            if variant.weight <= 0:
                raise ValidationError(f"Experiment '{experiment_key}' variant '{name}' must have positive weight")
            seen_names.add(name)
            total_weight += int(variant.weight)
            if name == "control":
                has_control = True
        if total_weight <= 0:
            raise ValidationError(f"Experiment '{experiment_key}' must have positive total variant weight")
        if not has_control:
            raise ValidationError(f"Experiment '{experiment_key}' must include a control variant")

    def _validate_experiment_key(self, experiment_key: str) -> str:
        normalized_key = (experiment_key or "").strip()
        if not _EXPERIMENT_KEY_PATTERN.match(normalized_key):
            raise ValidationError("Experiment key must match ^[a-z0-9_]{3,64}$")
        return normalized_key

    def _validate_transition(self, current_status: str | None, next_status: str) -> None:
        if current_status is None:
            return
        allowed_transitions = {
            "draft": {"draft", "active", "paused", "archived"},
            "active": {"active", "paused", "archived"},
            "paused": {"paused", "active", "archived"},
            "archived": {"archived"},
        }
        if next_status not in allowed_transitions.get(current_status, {current_status}):
            raise ValidationError(
                f"Experiment status cannot move from '{current_status}' to '{next_status}'"
            )

    def _normalize_actor(self, changed_by: str | None) -> str:
        actor = (changed_by or "").strip()
        if not actor:
            return "system_admin"
        return actor[:128]

    def _registry_config(self, registry) -> dict:
        if registry is None:
            return {}
        return {
            "experiment_key": str(registry.experiment_key),
            "status": str(registry.status),
            "rollout_percentage": int(registry.rollout_percentage),
            "is_killed": bool(registry.is_killed),
            "description": registry.description,
            "variants": [self._variant_payload_from_row(item) for item in list(registry.variants or [])],
            "created_at": self._timestamp(getattr(registry, "created_at", None)),
            "updated_at": self._timestamp(getattr(registry, "updated_at", None)),
        }

    def _registry_summary_payload(self, *, registry, assignment_counts: Counter, exposure_counts: Counter, latest_audit) -> dict:
        health = self._health_payload(
            assignment_counts=assignment_counts,
            exposure_counts=exposure_counts,
        )
        return {
            **self._registry_config(registry),
            "assignment_count": health["assignment_count"],
            "exposure_count": health["exposure_count"],
            "exposure_gap": health["exposure_gap"],
            "assignment_variants": health["assignment_variants"],
            "exposure_variants": health["exposure_variants"],
            "latest_change": self._audit_payload(latest_audit) if latest_audit is not None else None,
        }

    def _registry_detail_payload(self, *, registry, assignment_counts: Counter, exposure_counts: Counter, audits: list) -> dict:
        health = self._health_payload(
            assignment_counts=assignment_counts,
            exposure_counts=exposure_counts,
        )
        return {
            **self._registry_config(registry),
            "health": health,
            "audit_entries": [self._audit_payload(item) for item in audits],
        }

    def _health_payload(self, *, assignment_counts: Counter, exposure_counts: Counter) -> dict:
        assignment_count = int(sum(assignment_counts.values()))
        exposure_count = int(sum(exposure_counts.values()))
        return {
            "assignment_count": assignment_count,
            "exposure_count": exposure_count,
            "exposure_gap": max(0, assignment_count - exposure_count),
            "exposure_coverage_percent": round((exposure_count / assignment_count) * 100, 2) if assignment_count else 100.0,
            "assignment_variants": dict(sorted(assignment_counts.items())),
            "exposure_variants": dict(sorted(exposure_counts.items())),
        }

    def _variant_counts(self, rows: list) -> dict[str, Counter]:
        counts: dict[str, Counter] = {}
        for row in rows:
            experiment_key = str(row.experiment_key)
            variant = str(row.variant)
            counts.setdefault(experiment_key, Counter())[variant] += 1
        return counts

    def _audit_action(self, existing, command: ExperimentRegistryUpsert) -> str:
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
            "experiment_key": str(audit.experiment_key),
            "action": str(audit.action),
            "changed_by": str(audit.changed_by),
            "change_note": str(audit.change_note),
            "previous_config": dict(audit.previous_config or {}),
            "new_config": dict(audit.new_config or {}),
            "created_at": self._timestamp(audit.created_at),
        }

    def _variant_payload(self, variant: ExperimentRegistryVariantInput) -> dict:
        return {
            "name": variant.name.strip(),
            "weight": int(variant.weight),
        }

    def _variant_payload_from_row(self, variant: dict) -> dict:
        return {
            "name": str(variant.get("name") or ""),
            "weight": int(variant.get("weight") or 0),
        }

    def _timestamp(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
