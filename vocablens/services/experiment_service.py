from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.exc import IntegrityError

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.experiment_attribution_service import ExperimentAttributionService
from vocablens.services.learning_event_service import LearningEventService


@dataclass(frozen=True)
class ExperimentVariant:
    name: str
    weight: int


@dataclass(frozen=True)
class ExperimentDefinition:
    key: str
    status: str
    rollout_percentage: int
    holdout_percentage: int
    is_killed: bool
    baseline_variant: str
    eligibility: dict[str, tuple[str, ...]]
    mutually_exclusive_with: tuple[str, ...]
    prerequisite_experiments: tuple[str, ...]
    variants: tuple[ExperimentVariant, ...]


@dataclass(frozen=True)
class ExperimentContext:
    geography: str | None = None
    subscription_tier: str | None = None
    lifecycle_stage: str | None = None
    platform: str | None = None
    surface: str | None = None


class ExperimentService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        event_service: LearningEventService | None = None,
        attribution_service: ExperimentAttributionService | None = None,
        experiments: dict[str, dict[str, int] | ExperimentDefinition] | None = None,
    ):
        self._uow_factory = uow_factory
        self._events = event_service
        self._attribution = attribution_service or ExperimentAttributionService(uow_factory)
        source = experiments or {}
        self._experiment_overrides = {
            key: self._coerce_definition(key, definition)
            for key, definition in source.items()
        }

    async def assign(self, user_id: int, experiment_key: str, *, context: ExperimentContext | None = None) -> str:
        definition = await self._get_definition(experiment_key)
        assigned_at = utc_now()
        if not self._is_assignable(definition):
            raise KeyError(f"Experiment '{experiment_key}' is not assignable")
        async with self._uow_factory() as uow:
            assignment = await uow.experiment_assignments.get(user_id, experiment_key)
            if assignment is not None:
                await uow.commit()
                return assignment.variant
            resolved_context = await self._resolved_context(uow=uow, user_id=user_id, context=context)
            is_eligible = await self._is_eligible(uow=uow, user_id=user_id, definition=definition, context=resolved_context)
            if not is_eligible:
                await uow.commit()
                return self._baseline_variant(definition)
            if not self._is_in_rollout(user_id, definition):
                await uow.commit()
                return self._baseline_variant(definition)
            if self._is_in_holdout(user_id, definition):
                await uow.commit()
                variant, exposure_created = await self._ensure_assignment_and_exposure(
                    user_id=user_id,
                    experiment_key=experiment_key,
                    variant=self._baseline_variant(definition),
                    assigned_at=assigned_at,
                    assignment_reason="holdout",
                )
                if exposure_created and self._events:
                    await self._events.record(
                        event_type="experiment_exposure",
                        user_id=user_id,
                        payload={
                            "experiment_key": experiment_key,
                            "variant": variant,
                            "assigned_at": assigned_at.isoformat(),
                            "assignment_reason": "holdout",
                        },
                    )
                return variant
            await uow.commit()
        variant, exposure_created = await self._ensure_assignment_and_exposure(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=self._select_variant(user_id, definition),
            assigned_at=assigned_at,
            assignment_reason="rollout",
        )
        if exposure_created and self._events:
            await self._events.record(
                event_type="experiment_exposure",
                user_id=user_id,
                payload={
                    "experiment_key": experiment_key,
                    "variant": variant,
                    "assigned_at": assigned_at.isoformat(),
                    "assignment_reason": "rollout",
                },
            )
        return variant

    async def get_variant(self, user_id: int, experiment_key: str) -> str | None:
        async with self._uow_factory() as uow:
            assignment = await uow.experiment_assignments.get(user_id, experiment_key)
            await uow.commit()
        return assignment.variant if assignment else None

    async def get_exposure(self, user_id: int, experiment_key: str):
        async with self._uow_factory() as uow:
            exposure = await uow.experiment_exposures.get(user_id, experiment_key)
            await uow.commit()
        return exposure

    async def has_experiment(self, experiment_key: str) -> bool:
        try:
            definition = await self._get_definition(experiment_key)
        except KeyError:
            return False
        return self._is_assignable(definition)

    async def _ensure_assignment_and_exposure(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assigned_at: datetime,
        assignment_reason: str,
    ) -> tuple[str, bool]:
        try:
            async with self._uow_factory() as uow:
                assignment = await uow.experiment_assignments.get(user_id, experiment_key)
                exposure = await uow.experiment_exposures.get(user_id, experiment_key)
                assigned_variant = variant
                if assignment is None:
                    await uow.experiment_assignments.create(
                        user_id=user_id,
                        experiment_key=experiment_key,
                        variant=variant,
                        assigned_at=assigned_at,
                    )
                else:
                    assigned_variant = assignment.variant
                exposure_created = False
                if exposure is None:
                    await uow.experiment_exposures.create(
                        user_id=user_id,
                        experiment_key=experiment_key,
                        variant=assigned_variant,
                        exposed_at=assigned_at,
                    )
                    exposure_created = True
                await uow.commit()
                await self._attribution.ensure_exposure(
                    user_id=user_id,
                    experiment_key=experiment_key,
                    variant=assigned_variant,
                    exposed_at=assigned_at,
                    assignment_reason=assignment_reason,
                )
                return assigned_variant, exposure_created
        except IntegrityError:
            return await self._recover_assignment_and_exposure(
                user_id=user_id,
                experiment_key=experiment_key,
                assigned_at=assigned_at,
                assignment_reason=assignment_reason,
            )

    async def _recover_assignment_and_exposure(
        self,
        *,
        user_id: int,
        experiment_key: str,
        assigned_at: datetime,
        assignment_reason: str,
    ) -> tuple[str, bool]:
        async with self._uow_factory() as uow:
            assignment = await uow.experiment_assignments.get(user_id, experiment_key)
            if assignment is None:
                raise RuntimeError(f"Experiment assignment missing after integrity failure for '{experiment_key}'")
            exposure = await uow.experiment_exposures.get(user_id, experiment_key)
            exposure_created = False
            if exposure is None:
                try:
                    await uow.experiment_exposures.create(
                        user_id=user_id,
                        experiment_key=experiment_key,
                        variant=assignment.variant,
                        exposed_at=assigned_at,
                    )
                    exposure_created = True
                except IntegrityError:
                    exposure_created = False
            await uow.commit()
        await self._attribution.ensure_exposure(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=assignment.variant,
            exposed_at=assigned_at,
            assignment_reason=assignment_reason,
        )
        return assignment.variant, exposure_created

    async def _get_definition(self, experiment_key: str) -> ExperimentDefinition:
        override = self._experiment_overrides.get(experiment_key)
        if override is not None:
            return override
        async with self._uow_factory() as uow:
            registry = await uow.experiment_registries.get(experiment_key)
            await uow.commit()
        if registry is None:
            raise KeyError(f"Unknown experiment '{experiment_key}'")
        return self._coerce_registry_definition(registry)

    def _coerce_definition(
        self,
        key: str,
        definition: dict[str, int] | ExperimentDefinition,
    ) -> ExperimentDefinition:
        if isinstance(definition, ExperimentDefinition):
            self._validate_rollout(key, definition.rollout_percentage)
            self._validate_holdout(key, definition.holdout_percentage)
            self._validate_variants(key, definition.variants)
            if self._baseline_variant(definition) not in {variant.name for variant in definition.variants}:
                raise ValueError(f"Experiment '{key}' baseline variant must exist in variants")
            return definition
        variants = tuple(
            ExperimentVariant(name=name, weight=int(weight))
            for name, weight in definition.items()
        )
        self._validate_variants(key, variants)
        return ExperimentDefinition(
            key=key,
            status="active",
            rollout_percentage=100,
            holdout_percentage=0,
            is_killed=False,
            baseline_variant="control" if any(variant.name == "control" for variant in variants) else variants[0].name,
            eligibility={},
            mutually_exclusive_with=(),
            prerequisite_experiments=(),
            variants=variants,
        )

    def _coerce_registry_definition(self, registry) -> ExperimentDefinition:
        variants = tuple(
            ExperimentVariant(
                name=str(item["name"]),
                weight=int(item["weight"]),
            )
            for item in list(getattr(registry, "variants", []) or [])
        )
        definition = ExperimentDefinition(
            key=str(registry.experiment_key),
            status=str(registry.status),
            rollout_percentage=int(registry.rollout_percentage),
            holdout_percentage=int(getattr(registry, "holdout_percentage", 0) or 0),
            is_killed=bool(registry.is_killed),
            baseline_variant=str(getattr(registry, "baseline_variant", "control") or "control"),
            eligibility=self._coerce_eligibility(getattr(registry, "eligibility", {}) or {}),
            mutually_exclusive_with=tuple(str(item) for item in list(getattr(registry, "mutually_exclusive_with", []) or [])),
            prerequisite_experiments=tuple(str(item) for item in list(getattr(registry, "prerequisite_experiments", []) or [])),
            variants=variants,
        )
        self._validate_rollout(definition.key, definition.rollout_percentage)
        self._validate_holdout(definition.key, definition.holdout_percentage)
        self._validate_variants(definition.key, definition.variants)
        if self._baseline_variant(definition) not in {variant.name for variant in definition.variants}:
            raise ValueError(f"Experiment '{definition.key}' baseline variant must exist in variants")
        return definition

    def _validate_variants(self, key: str, variants: Iterable[ExperimentVariant]) -> None:
        materialized = tuple(variants)
        if not materialized:
            raise ValueError(f"Experiment '{key}' must declare at least one variant")
        total_weight = 0
        seen_names: set[str] = set()
        for variant in materialized:
            if not variant.name:
                raise ValueError(f"Experiment '{key}' contains an empty variant name")
            if variant.name in seen_names:
                raise ValueError(f"Experiment '{key}' contains duplicate variant '{variant.name}'")
            if variant.weight <= 0:
                raise ValueError(f"Experiment '{key}' variant '{variant.name}' must have positive weight")
            seen_names.add(variant.name)
            total_weight += variant.weight
        if total_weight <= 0:
            raise ValueError(f"Experiment '{key}' must have positive total weight")

    def _validate_rollout(self, key: str, rollout_percentage: int) -> None:
        if rollout_percentage < 0 or rollout_percentage > 100:
            raise ValueError(f"Experiment '{key}' rollout percentage must be between 0 and 100")

    def _validate_holdout(self, key: str, holdout_percentage: int) -> None:
        if holdout_percentage < 0 or holdout_percentage >= 100:
            raise ValueError(f"Experiment '{key}' holdout percentage must be between 0 and 99")

    def _is_assignable(self, definition: ExperimentDefinition) -> bool:
        return definition.status == "active" and not definition.is_killed and definition.rollout_percentage > 0

    def _is_in_rollout(self, user_id: int, definition: ExperimentDefinition) -> bool:
        if definition.rollout_percentage >= 100:
            return True
        digest = hashlib.sha256(f"{definition.key}:rollout:{user_id}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return bucket < definition.rollout_percentage

    def _baseline_variant(self, definition: ExperimentDefinition) -> str:
        if definition.baseline_variant:
            return definition.baseline_variant
        for variant in definition.variants:
            if variant.name == "control":
                return variant.name
        return definition.variants[0].name

    def _is_in_holdout(self, user_id: int, definition: ExperimentDefinition) -> bool:
        if definition.holdout_percentage <= 0:
            return False
        digest = hashlib.sha256(f"{definition.key}:holdout:{user_id}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return bucket < definition.holdout_percentage

    def _select_variant(self, user_id: int, definition: ExperimentDefinition) -> str:
        total_weight = sum(variant.weight for variant in definition.variants)
        digest = hashlib.sha256(f"{definition.key}:{user_id}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % total_weight
        running_total = 0
        for variant in definition.variants:
            running_total += variant.weight
            if bucket < running_total:
                return variant.name
        return definition.variants[-1].name

    def _coerce_eligibility(self, raw: dict) -> dict[str, tuple[str, ...]]:
        return {
            str(key): tuple(str(item) for item in list(values or []))
            for key, values in dict(raw or {}).items()
        }

    async def _resolved_context(
        self,
        *,
        uow,
        user_id: int,
        context: ExperimentContext | None,
    ) -> ExperimentContext:
        context = context or ExperimentContext()
        subscription_tier = context.subscription_tier
        lifecycle_stage = context.lifecycle_stage
        if subscription_tier is None:
            subscription = await uow.subscriptions.get_by_user(user_id)
            subscription_tier = str(getattr(subscription, "tier", "free") or "free")
        if lifecycle_stage is None:
            lifecycle_state = await uow.lifecycle_states.get(user_id)
            lifecycle_stage = str(getattr(lifecycle_state, "current_stage", "") or "") or None
        return ExperimentContext(
            geography=context.geography,
            subscription_tier=subscription_tier,
            lifecycle_stage=lifecycle_stage,
            platform=context.platform,
            surface=context.surface,
        )

    async def _is_eligible(
        self,
        *,
        uow,
        user_id: int,
        definition: ExperimentDefinition,
        context: ExperimentContext,
    ) -> bool:
        if not self._matches_eligibility(definition, context):
            return False
        if definition.prerequisite_experiments:
            for experiment_key in definition.prerequisite_experiments:
                prerequisite = await uow.experiment_assignments.get(user_id, experiment_key)
                if prerequisite is None:
                    return False
        if definition.mutually_exclusive_with:
            for experiment_key in definition.mutually_exclusive_with:
                conflicting = await uow.experiment_assignments.get(user_id, experiment_key)
                if conflicting is not None:
                    return False
        return True

    def _matches_eligibility(self, definition: ExperimentDefinition, context: ExperimentContext) -> bool:
        eligibility = definition.eligibility
        if not eligibility:
            return True
        checks = {
            "geographies": context.geography,
            "subscription_tiers": context.subscription_tier,
            "lifecycle_stages": context.lifecycle_stage,
            "platforms": context.platform,
            "surfaces": context.surface,
        }
        for field_name, allowed_values in eligibility.items():
            current_value = checks.get(field_name)
            if current_value is None:
                return False
            if str(current_value) not in allowed_values:
                return False
        return True
