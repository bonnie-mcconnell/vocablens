from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import math
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
    holdout_percentage: int = 0
    baseline_variant: str = "control"
    eligibility: dict[str, tuple[str, ...]] | None = None
    mutually_exclusive_with: tuple[str, ...] = ()
    prerequisite_experiments: tuple[str, ...] = ()


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
                holdout_percentage=command.holdout_percentage,
                is_killed=command.is_killed,
                baseline_variant=command.baseline_variant.strip(),
                description=command.description,
                variants=[self._variant_payload(item) for item in command.variants],
                eligibility=self._eligibility_payload(command.eligibility or {}),
                mutually_exclusive_with=list(command.mutually_exclusive_with),
                prerequisite_experiments=list(command.prerequisite_experiments),
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

    async def pause_registry(
        self,
        *,
        experiment_key: str,
        changed_by: str | None,
        change_note: str,
    ) -> dict:
        return await self._apply_existing_action(
            experiment_key=experiment_key,
            changed_by=changed_by,
            change_note=change_note,
            status="paused",
        )

    async def resume_registry(
        self,
        *,
        experiment_key: str,
        changed_by: str | None,
        change_note: str,
    ) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        async with self._uow_factory() as uow:
            existing = await uow.experiment_registries.get(normalized_key)
            if existing is None:
                raise NotFoundError(f"Experiment '{normalized_key}' not found")
            if bool(existing.is_killed):
                raise ValidationError(f"Experiment '{normalized_key}' cannot resume while kill switch is enabled")
            await uow.commit()

        return await self._apply_existing_action(
            experiment_key=normalized_key,
            changed_by=changed_by,
            change_note=change_note,
            status="active",
        )

    async def kill_registry(
        self,
        *,
        experiment_key: str,
        changed_by: str | None,
        change_note: str,
    ) -> dict:
        return await self._apply_existing_action(
            experiment_key=experiment_key,
            changed_by=changed_by,
            change_note=change_note,
            is_killed=True,
        )

    async def archive_registry(
        self,
        *,
        experiment_key: str,
        changed_by: str | None,
        change_note: str,
    ) -> dict:
        return await self._apply_existing_action(
            experiment_key=experiment_key,
            changed_by=changed_by,
            change_note=change_note,
            status="archived",
        )

    async def list_audit_history(self, experiment_key: str, *, limit: int = 50) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        async with self._uow_factory() as uow:
            registry = await uow.experiment_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Experiment '{normalized_key}' not found")
            audits = await uow.experiment_registry_audits.list_by_experiment(normalized_key, limit=max(1, min(limit, 200)))
            await uow.commit()
        return {"audit_entries": [self._audit_payload(item) for item in audits]}

    async def get_operator_report(self, experiment_key: str, *, limit: int = 50) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            registry = await uow.experiment_registries.get(normalized_key)
            if registry is None:
                raise NotFoundError(f"Experiment '{normalized_key}' not found")
            assignments = await uow.experiment_assignments.list_all(normalized_key)
            exposures = await uow.experiment_exposures.list_all(normalized_key)
            audits = await uow.experiment_registry_audits.list_by_experiment(normalized_key, limit=20)
            attributions = await uow.experiment_outcome_attributions.list_all(normalized_key)
            traces = await uow.decision_traces.list_recent(
                trace_type="experiment_assignment",
                reference_id=normalized_key,
                limit=normalized_limit,
            )
            await uow.commit()

        assignment_counts = self._variant_counts(assignments).get(normalized_key, Counter())
        exposure_counts = self._variant_counts(exposures).get(normalized_key, Counter())
        return {
            "experiment": {
                **self._registry_detail_payload(
                    registry=registry,
                    assignment_counts=assignment_counts,
                    exposure_counts=exposure_counts,
                    audits=audits,
                ),
                "results": self._results_payload(registry=registry, attributions=attributions),
                "attribution_summary": self._attribution_summary_payload(attributions),
                "recent_exposures": self._recent_attributions_payload(attributions, limit=normalized_limit),
                "latest_assignment_trace": self._trace_payload(traces[0]) if traces else None,
                "assignment_traces": [self._trace_payload(item) for item in traces],
            }
        }

    async def get_health_dashboard(self, *, limit: int = 50) -> dict:
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            registries = await uow.experiment_registries.list_all()
            health_states = await uow.experiment_health_states.list_all()
            latest_audits = {}
            for registry in registries:
                latest_audits[registry.experiment_key] = await uow.experiment_registry_audits.latest_for_experiment(
                    registry.experiment_key
                )
            await uow.commit()

        state_by_key = {str(item.experiment_key): item for item in health_states}
        rows = [
            self._dashboard_experiment_payload(
                registry,
                latest_audit=latest_audits.get(registry.experiment_key),
                health_state=state_by_key.get(str(registry.experiment_key)),
            )
            for registry in registries
        ]
        rows.sort(key=lambda item: (self._health_status_rank(item["health_status"]), item["experiment_key"]))
        counts_by_status = Counter(str(item.get("health_status") or "unevaluated") for item in rows)
        alert_code_counts = Counter()
        for row in rows:
            for code in row.get("latest_alert_codes", []):
                alert_code_counts[str(code)] += 1
        return {
            "summary": {
                "total_experiments": len(rows),
                "counts_by_health_status": dict(sorted(counts_by_status.items())),
                "experiments_with_alerts": sum(1 for row in rows if row.get("latest_alert_codes")),
                "alert_counts_by_code": dict(sorted(alert_code_counts.items())),
                "latest_evaluated_at": max((row.get("last_evaluated_at") for row in rows if row.get("last_evaluated_at")), default=None),
            },
            "attention": [row for row in rows if row["health_status"] != "healthy"][:normalized_limit],
            "experiments": rows[:normalized_limit],
        }

    def _validate_command(self, experiment_key: str, command: ExperimentRegistryUpsert) -> None:
        if command.status not in _VALID_STATUSES:
            raise ValidationError(f"Experiment '{experiment_key}' has invalid status '{command.status}'")
        if command.rollout_percentage < 0 or command.rollout_percentage > 100:
            raise ValidationError(f"Experiment '{experiment_key}' rollout percentage must be between 0 and 100")
        if command.holdout_percentage < 0 or command.holdout_percentage > 100:
            raise ValidationError(f"Experiment '{experiment_key}' holdout percentage must be between 0 and 100")
        note = (command.change_note or "").strip()
        if len(note) < 8:
            raise ValidationError("Change note must be at least 8 characters")
        description = (command.description or "").strip()
        if command.description is not None and len(description) > 1000:
            raise ValidationError("Description must be 1000 characters or fewer")
        if command.status == "active" and not command.is_killed and command.rollout_percentage == 0:
            raise ValidationError("Active experiments must have rollout percentage greater than 0 unless killed")
        if command.holdout_percentage >= 100:
            raise ValidationError("Holdout percentage must stay below 100")
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
        baseline_variant = (command.baseline_variant or "").strip()
        if not baseline_variant:
            raise ValidationError(f"Experiment '{experiment_key}' must declare a baseline variant")
        if baseline_variant not in seen_names:
            raise ValidationError(f"Experiment '{experiment_key}' baseline variant must exist in variants")
        self._validate_key_list(
            experiment_key,
            values=command.mutually_exclusive_with,
            field_name="mutually_exclusive_with",
            allow_self=False,
        )
        self._validate_key_list(
            experiment_key,
            values=command.prerequisite_experiments,
            field_name="prerequisite_experiments",
            allow_self=False,
        )
        self._validate_eligibility(experiment_key, command.eligibility or {})

    async def _apply_existing_action(
        self,
        *,
        experiment_key: str,
        changed_by: str | None,
        change_note: str,
        status: str | None = None,
        is_killed: bool | None = None,
    ) -> dict:
        normalized_key = self._validate_experiment_key(experiment_key)
        async with self._uow_factory() as uow:
            existing = await uow.experiment_registries.get(normalized_key)
            if existing is None:
                raise NotFoundError(f"Experiment '{normalized_key}' not found")
            await uow.commit()

        command = ExperimentRegistryUpsert(
            status=status or str(existing.status),
            rollout_percentage=int(existing.rollout_percentage),
            holdout_percentage=int(getattr(existing, "holdout_percentage", 0) or 0),
            is_killed=bool(existing.is_killed) if is_killed is None else is_killed,
            baseline_variant=str(getattr(existing, "baseline_variant", "control") or "control"),
            description=existing.description,
            variants=tuple(
                ExperimentRegistryVariantInput(
                    name=str(item.get("name") or ""),
                    weight=int(item.get("weight") or 0),
                )
                for item in list(existing.variants or [])
            ),
            eligibility={
                str(key): tuple(str(item) for item in list(values or []))
                for key, values in dict(getattr(existing, "eligibility", {}) or {}).items()
            },
            mutually_exclusive_with=tuple(
                str(item) for item in list(getattr(existing, "mutually_exclusive_with", []) or [])
            ),
            prerequisite_experiments=tuple(
                str(item) for item in list(getattr(existing, "prerequisite_experiments", []) or [])
            ),
            change_note=change_note,
        )
        return await self.upsert_registry(
            experiment_key=normalized_key,
            command=command,
            changed_by=changed_by,
        )

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
            "holdout_percentage": int(getattr(registry, "holdout_percentage", 0) or 0),
            "is_killed": bool(registry.is_killed),
            "baseline_variant": str(getattr(registry, "baseline_variant", "control") or "control"),
            "description": registry.description,
            "variants": [self._variant_payload_from_row(item) for item in list(registry.variants or [])],
            "eligibility": self._eligibility_payload_from_row(getattr(registry, "eligibility", {}) or {}),
            "mutually_exclusive_with": [str(item) for item in list(getattr(registry, "mutually_exclusive_with", []) or [])],
            "prerequisite_experiments": [str(item) for item in list(getattr(registry, "prerequisite_experiments", []) or [])],
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

    def _results_payload(self, *, registry, attributions: list) -> dict:
        grouped: dict[str, list] = {}
        for row in attributions:
            grouped.setdefault(str(row.variant), []).append(row)
        baseline_variant = str(getattr(registry, "baseline_variant", "control") or "control")
        raw_variants = [
            self._result_variant_payload(
                experiment_key=str(registry.experiment_key),
                variant=variant,
                rows=rows,
            )
            for variant, rows in sorted(
                grouped.items(),
                key=lambda item: (0 if item[0] == baseline_variant else 1, item[0]),
            )
        ]
        return {
            "experiment_key": str(registry.experiment_key),
            "variants": [self._public_result_variant_payload(item) for item in raw_variants],
            "comparisons": self._comparison_payloads(raw_variants),
        }

    def _result_variant_payload(self, *, experiment_key: str, variant: str, rows: list) -> dict:
        user_count = len(rows)
        retained = sum(1 for row in rows if bool(getattr(row, "retained_d1", False)))
        converted = sum(1 for row in rows if bool(getattr(row, "converted", False)))
        denominator = max(1, user_count)
        return {
            "experiment_key": experiment_key,
            "variant": variant,
            "users": user_count,
            "retention_rate": round((retained / denominator) * 100, 1),
            "conversion_rate": round((converted / denominator) * 100, 1),
            "engagement": {
                "sessions_per_user": round(sum(int(getattr(row, "session_count", 0) or 0) for row in rows) / denominator, 2),
                "messages_per_user": round(sum(int(getattr(row, "message_count", 0) or 0) for row in rows) / denominator, 2),
                "learning_actions_per_user": round(
                    sum(int(getattr(row, "learning_action_count", 0) or 0) for row in rows) / denominator,
                    2,
                ),
            },
            "_retained": retained,
            "_converted": converted,
        }

    def _public_result_variant_payload(self, variant: dict) -> dict:
        return {
            "experiment_key": variant["experiment_key"],
            "variant": variant["variant"],
            "users": variant["users"],
            "retention_rate": variant["retention_rate"],
            "conversion_rate": variant["conversion_rate"],
            "engagement": dict(variant["engagement"]),
        }

    def _comparison_payloads(self, variants: list[dict]) -> list[dict]:
        if len(variants) < 2:
            return []
        base = variants[0]
        comparisons = []
        for candidate in variants[1:]:
            comparisons.append(
                {
                    "baseline_variant": base["variant"],
                    "candidate_variant": candidate["variant"],
                    "retention_lift": round(candidate["retention_rate"] - base["retention_rate"], 1),
                    "conversion_lift": round(candidate["conversion_rate"] - base["conversion_rate"], 1),
                    "retention_significance": self._significance_payload(
                        base["_retained"],
                        base["users"],
                        candidate["_retained"],
                        candidate["users"],
                    ),
                    "conversion_significance": self._significance_payload(
                        base["_converted"],
                        base["users"],
                        candidate["_converted"],
                        candidate["users"],
                    ),
                }
            )
        return comparisons

    def _significance_payload(self, success_a: int, total_a: int, success_b: int, total_b: int) -> dict:
        if total_a <= 0 or total_b <= 0:
            return {"z_score": 0.0, "is_significant": False}
        pooled = (success_a + success_b) / (total_a + total_b)
        variance = pooled * (1 - pooled) * ((1 / total_a) + (1 / total_b))
        if variance <= 0:
            return {"z_score": 0.0, "is_significant": False}
        z_score = ((success_b / total_b) - (success_a / total_a)) / math.sqrt(variance)
        return {
            "z_score": round(z_score, 3),
            "is_significant": abs(z_score) >= 1.96,
        }

    def _attribution_summary_payload(self, attributions: list) -> dict:
        total_users = len(attributions)
        return {
            "users": total_users,
            "retained_d1_users": sum(1 for row in attributions if bool(getattr(row, "retained_d1", False))),
            "retained_d7_users": sum(1 for row in attributions if bool(getattr(row, "retained_d7", False))),
            "converted_users": sum(1 for row in attributions if bool(getattr(row, "converted", False))),
            "sessions": sum(int(getattr(row, "session_count", 0) or 0) for row in attributions),
            "messages": sum(int(getattr(row, "message_count", 0) or 0) for row in attributions),
            "learning_actions": sum(int(getattr(row, "learning_action_count", 0) or 0) for row in attributions),
            "upgrade_clicks": sum(int(getattr(row, "upgrade_click_count", 0) or 0) for row in attributions),
        }

    def _recent_attributions_payload(self, attributions: list, *, limit: int) -> list[dict]:
        rows = sorted(
            attributions,
            key=lambda item: (
                self._timestamp(getattr(item, "exposed_at", None)) or "",
                int(getattr(item, "user_id", 0) or 0),
            ),
            reverse=True,
        )
        return [self._attribution_payload(item) for item in rows[:limit]]

    def _attribution_payload(self, attribution) -> dict:
        return {
            "user_id": int(attribution.user_id),
            "variant": str(attribution.variant),
            "assignment_reason": str(getattr(attribution, "assignment_reason", "rollout") or "rollout"),
            "attribution_version": str(getattr(attribution, "attribution_version", "v1") or "v1"),
            "exposed_at": self._timestamp(getattr(attribution, "exposed_at", None)),
            "window_end_at": self._timestamp(getattr(attribution, "window_end_at", None)),
            "retained_d1": bool(getattr(attribution, "retained_d1", False)),
            "retained_d7": bool(getattr(attribution, "retained_d7", False)),
            "converted": bool(getattr(attribution, "converted", False)),
            "first_conversion_at": self._timestamp(getattr(attribution, "first_conversion_at", None)),
            "session_count": int(getattr(attribution, "session_count", 0) or 0),
            "message_count": int(getattr(attribution, "message_count", 0) or 0),
            "learning_action_count": int(getattr(attribution, "learning_action_count", 0) or 0),
            "upgrade_click_count": int(getattr(attribution, "upgrade_click_count", 0) or 0),
            "last_event_at": self._timestamp(getattr(attribution, "last_event_at", None)),
        }

    def _trace_payload(self, trace) -> dict:
        return {
            "id": int(trace.id),
            "user_id": int(trace.user_id),
            "trace_type": str(trace.trace_type),
            "source": str(trace.source),
            "reference_id": str(trace.reference_id) if getattr(trace, "reference_id", None) is not None else None,
            "policy_version": str(trace.policy_version),
            "inputs": dict(getattr(trace, "inputs", {}) or {}),
            "outputs": dict(getattr(trace, "outputs", {}) or {}),
            "reason": str(trace.reason) if getattr(trace, "reason", None) is not None else None,
            "created_at": self._timestamp(getattr(trace, "created_at", None)),
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

    def _validate_key_list(
        self,
        experiment_key: str,
        *,
        values: tuple[str, ...],
        field_name: str,
        allow_self: bool,
    ) -> None:
        seen: set[str] = set()
        for value in values:
            normalized = self._validate_experiment_key(value)
            if not allow_self and normalized == experiment_key:
                raise ValidationError(f"Experiment '{experiment_key}' cannot include itself in {field_name}")
            if normalized in seen:
                raise ValidationError(f"Experiment '{experiment_key}' contains duplicate entries in {field_name}")
            seen.add(normalized)

    def _validate_eligibility(self, experiment_key: str, eligibility: dict[str, tuple[str, ...]]) -> None:
        allowed_fields = {"geographies", "subscription_tiers", "lifecycle_stages", "platforms", "surfaces"}
        for field_name, values in eligibility.items():
            if field_name not in allowed_fields:
                raise ValidationError(f"Experiment '{experiment_key}' has unsupported eligibility field '{field_name}'")
            normalized_values = [str(value).strip() for value in values if str(value).strip()]
            if len(normalized_values) != len(set(normalized_values)):
                raise ValidationError(f"Experiment '{experiment_key}' contains duplicate eligibility values for '{field_name}'")
            if not normalized_values:
                raise ValidationError(f"Experiment '{experiment_key}' has an empty eligibility list for '{field_name}'")

    def _eligibility_payload(self, eligibility: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
        return {
            key: [str(item).strip() for item in values]
            for key, values in sorted(eligibility.items())
            if values
        }

    def _eligibility_payload_from_row(self, eligibility: dict) -> dict[str, list[str]]:
        return {
            str(key): [str(item) for item in list(values or [])]
            for key, values in dict(eligibility or {}).items()
        }

    def _timestamp(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def _dashboard_experiment_payload(self, registry, *, latest_audit, health_state) -> dict:
        return {
            "experiment_key": str(registry.experiment_key),
            "registry_status": str(registry.status),
            "health_status": str(getattr(health_state, "current_status", "unevaluated") or "unevaluated"),
            "is_killed": bool(registry.is_killed),
            "rollout_percentage": int(registry.rollout_percentage or 0),
            "holdout_percentage": int(getattr(registry, "holdout_percentage", 0) or 0),
            "baseline_variant": str(getattr(registry, "baseline_variant", "control") or "control"),
            "description": registry.description,
            "latest_alert_codes": list(getattr(health_state, "latest_alert_codes", []) or []),
            "metrics": dict(getattr(health_state, "metrics", {}) or {}),
            "last_evaluated_at": self._timestamp(getattr(health_state, "last_evaluated_at", None)),
            "updated_at": self._timestamp(getattr(registry, "updated_at", None)),
            "latest_change_note": getattr(latest_audit, "change_note", None),
        }

    def _health_status_rank(self, status: str) -> int:
        ranking = {
            "critical": 0,
            "warning": 1,
            "healthy": 2,
            "unevaluated": 3,
        }
        return ranking.get(status, 4)
