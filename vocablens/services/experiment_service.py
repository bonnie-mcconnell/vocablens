from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.exc import IntegrityError

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
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
    is_killed: bool
    variants: tuple[ExperimentVariant, ...]


class ExperimentService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        event_service: LearningEventService | None = None,
        experiments: dict[str, dict[str, int] | ExperimentDefinition] | None = None,
    ):
        self._uow_factory = uow_factory
        self._events = event_service
        source = experiments or {}
        self._experiment_overrides = {
            key: self._coerce_definition(key, definition)
            for key, definition in source.items()
        }

    async def assign(self, user_id: int, experiment_key: str) -> str:
        definition = await self._get_definition(experiment_key)
        assigned_at = utc_now()
        if not self._is_assignable(definition):
            raise KeyError(f"Experiment '{experiment_key}' is not assignable")
        if not self._is_in_rollout(user_id, definition):
            return self._baseline_variant(definition)
        variant, exposure_created = await self._ensure_assignment_and_exposure(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=self._select_variant(user_id, definition),
            assigned_at=assigned_at,
        )
        if exposure_created and self._events:
            await self._events.record(
                event_type="experiment_exposure",
                user_id=user_id,
                payload={
                    "experiment_key": experiment_key,
                    "variant": variant,
                    "assigned_at": assigned_at.isoformat(),
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
                return assigned_variant, exposure_created
        except IntegrityError:
            return await self._recover_assignment_and_exposure(
                user_id=user_id,
                experiment_key=experiment_key,
                assigned_at=assigned_at,
            )

    async def _recover_assignment_and_exposure(
        self,
        *,
        user_id: int,
        experiment_key: str,
        assigned_at: datetime,
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
            self._validate_variants(key, definition.variants)
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
            is_killed=False,
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
            is_killed=bool(registry.is_killed),
            variants=variants,
        )
        self._validate_rollout(definition.key, definition.rollout_percentage)
        self._validate_variants(definition.key, definition.variants)
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

    def _is_assignable(self, definition: ExperimentDefinition) -> bool:
        return definition.status == "active" and not definition.is_killed and definition.rollout_percentage > 0

    def _is_in_rollout(self, user_id: int, definition: ExperimentDefinition) -> bool:
        if definition.rollout_percentage >= 100:
            return True
        digest = hashlib.sha256(f"{definition.key}:rollout:{user_id}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return bucket < definition.rollout_percentage

    def _baseline_variant(self, definition: ExperimentDefinition) -> str:
        for variant in definition.variants:
            if variant.name == "control":
                return variant.name
        return definition.variants[0].name

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
