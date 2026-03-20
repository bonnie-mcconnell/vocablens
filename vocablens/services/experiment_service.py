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
    variants: tuple[ExperimentVariant, ...]


DEFAULT_EXPERIMENTS = {
    "learning_strategy": {"control": 100},
    "retention_nudges": {"control": 100},
    "paywall_offer": {"control": 100},
    "paywall_trigger_timing": {"control": 100},
    "paywall_trial_length": {"control": 100},
    "paywall_pricing_messaging": {"control": 100},
}


class ExperimentService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        event_service: LearningEventService | None = None,
        experiments: dict[str, dict[str, int] | ExperimentDefinition] | None = None,
    ):
        self._uow_factory = uow_factory
        self._events = event_service
        source = experiments or DEFAULT_EXPERIMENTS
        self._experiments = {
            key: self._coerce_definition(key, definition)
            for key, definition in source.items()
        }

    async def assign(self, user_id: int, experiment_key: str) -> str:
        definition = self._get_definition(experiment_key)
        existing = await self.get_variant(user_id, experiment_key)
        if existing is not None:
            return existing

        assigned_at = utc_now()
        variant = self._select_variant(user_id, definition)
        created = await self._create_assignment(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            assigned_at=assigned_at,
        )
        if created and self._events:
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

    def has_experiment(self, experiment_key: str) -> bool:
        return experiment_key in self._experiments

    async def _create_assignment(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assigned_at: datetime,
    ) -> bool:
        try:
            async with self._uow_factory() as uow:
                existing = await uow.experiment_assignments.get(user_id, experiment_key)
                if existing is not None:
                    await uow.commit()
                    return False
                await uow.experiment_assignments.create(
                    user_id=user_id,
                    experiment_key=experiment_key,
                    variant=variant,
                    assigned_at=assigned_at,
                )
                await uow.commit()
                return True
        except IntegrityError:
            return False

    def _get_definition(self, experiment_key: str) -> ExperimentDefinition:
        try:
            return self._experiments[experiment_key]
        except KeyError as exc:
            raise KeyError(f"Unknown experiment '{experiment_key}'") from exc

    def _coerce_definition(
        self,
        key: str,
        definition: dict[str, int] | ExperimentDefinition,
    ) -> ExperimentDefinition:
        if isinstance(definition, ExperimentDefinition):
            variants = definition.variants
        else:
            variants = tuple(
                ExperimentVariant(name=name, weight=int(weight))
                for name, weight in definition.items()
            )
        self._validate_variants(key, variants)
        return ExperimentDefinition(key=key, variants=variants)

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
