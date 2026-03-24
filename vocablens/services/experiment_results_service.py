from __future__ import annotations

import math
from collections import defaultdict

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.report_models import (
    ExperimentComparison,
    ExperimentResult,
    ExperimentResultsReport,
    ExperimentSignificance,
    ExperimentVariantEngagement,
    ExperimentVariantResult,
)


class ExperimentResultsService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def results(self, experiment_key: str | None = None) -> ExperimentResultsReport:
        async with self._uow_factory() as uow:
            attributions = await uow.experiment_outcome_attributions.list_all(experiment_key)
            registries = await uow.experiment_registries.list_all()
            await uow.commit()

        grouped = self._group_attributions(attributions)
        baselines = {
            str(registry.experiment_key): str(getattr(registry, "baseline_variant", "control") or "control")
            for registry in registries
        }
        experiments: list[ExperimentResult] = []
        for key, variant_rows in grouped.items():
            raw_variants = []
            baseline_variant = baselines.get(key, "control")
            for variant, attribution_rows in sorted(
                variant_rows.items(),
                key=lambda item: (0 if item[0] == baseline_variant else 1, item[0]),
            ):
                raw_variants.append(
                    self._variant_metrics(
                        experiment_key=key,
                        variant=variant,
                        attributions=attribution_rows,
                    )
                )
            experiments.append(
                ExperimentResult(
                    experiment_key=key,
                    variants=[self._public_variant(variant) for variant in raw_variants],
                    comparisons=self._comparisons(raw_variants),
                )
            )
        return ExperimentResultsReport(experiments=experiments)

    def _group_attributions(self, attributions) -> dict[str, dict[str, list]]:
        grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for attribution in attributions:
            grouped[attribution.experiment_key][attribution.variant].append(attribution)
        return grouped

    def _variant_metrics(self, *, experiment_key: str, variant: str, attributions) -> dict:
        user_count = len(attributions)
        retained = sum(1 for row in attributions if bool(getattr(row, "retained_d1", False)))
        converted = sum(1 for row in attributions if bool(getattr(row, "converted", False)))
        total_sessions = sum(int(getattr(row, "session_count", 0) or 0) for row in attributions)
        total_messages = sum(int(getattr(row, "message_count", 0) or 0) for row in attributions)
        total_learning_actions = sum(int(getattr(row, "learning_action_count", 0) or 0) for row in attributions)
        denominator = max(1, user_count)
        return {
            "experiment_key": experiment_key,
            "variant": variant,
            "users": user_count,
            "retention_rate": round((retained / denominator) * 100, 1),
            "conversion_rate": round((converted / denominator) * 100, 1),
            "engagement": {
                "sessions_per_user": round(total_sessions / denominator, 2),
                "messages_per_user": round(total_messages / denominator, 2),
                "learning_actions_per_user": round(total_learning_actions / denominator, 2),
            },
            "_retained": retained,
            "_converted": converted,
        }

    def _comparisons(self, variants: list[dict]) -> list[ExperimentComparison]:
        if len(variants) < 2:
            return []
        base = variants[0]
        comparisons: list[ExperimentComparison] = []
        for candidate in variants[1:]:
            comparisons.append(
                ExperimentComparison(
                    baseline_variant=base["variant"],
                    candidate_variant=candidate["variant"],
                    retention_lift=round(candidate["retention_rate"] - base["retention_rate"], 1),
                    conversion_lift=round(candidate["conversion_rate"] - base["conversion_rate"], 1),
                    retention_significance=self._basic_significance(
                        base["_retained"],
                        base["users"],
                        candidate["_retained"],
                        candidate["users"],
                    ),
                    conversion_significance=self._basic_significance(
                        base["_converted"],
                        base["users"],
                        candidate["_converted"],
                        candidate["users"],
                    ),
                )
            )
        return comparisons

    def _public_variant(self, variant: dict) -> ExperimentVariantResult:
        return ExperimentVariantResult(
            experiment_key=variant["experiment_key"],
            variant=variant["variant"],
            users=variant["users"],
            retention_rate=variant["retention_rate"],
            conversion_rate=variant["conversion_rate"],
            engagement=ExperimentVariantEngagement(**variant["engagement"]),
        )

    def _basic_significance(self, success_a: int, total_a: int, success_b: int, total_b: int) -> ExperimentSignificance:
        if total_a <= 0 or total_b <= 0:
            return ExperimentSignificance()
        p_a = success_a / total_a
        p_b = success_b / total_b
        pooled = (success_a + success_b) / (total_a + total_b)
        variance = pooled * (1 - pooled) * ((1 / total_a) + (1 / total_b))
        if variance <= 0:
            return ExperimentSignificance()
        z_score = (p_b - p_a) / math.sqrt(variance)
        return ExperimentSignificance(
            z_score=round(z_score, 3),
            is_significant=abs(z_score) >= 1.96,
        )
