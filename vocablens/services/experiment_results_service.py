from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


class ExperimentResultsService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def results(self, experiment_key: str | None = None) -> dict:
        async with self._uow_factory() as uow:
            assignments = await uow.experiment_assignments.list_all(experiment_key)
            events = await uow.events.list_since(
                utc_now() - timedelta(days=90),
                event_types=[
                    "session_started",
                    "message_sent",
                    "lesson_completed",
                    "review_completed",
                    "upgrade_clicked",
                    "upgrade_completed",
                    "subscription_upgraded",
                ],
                limit=50000,
            )
            await uow.commit()

        grouped = self._group_assignments(assignments)
        user_events = self._group_events_by_user(events)
        experiments = []
        for key, variant_rows in grouped.items():
            raw_variants = []
            for variant, variant_assignments in sorted(variant_rows.items()):
                raw_variants.append(
                    self._variant_metrics(
                        experiment_key=key,
                        variant=variant,
                        assignments=variant_assignments,
                        user_events=user_events,
                    )
                )
            experiments.append(
                {
                    "experiment_key": key,
                    "variants": [self._public_variant(variant) for variant in raw_variants],
                    "comparisons": self._comparisons(raw_variants),
                }
            )
        return {"experiments": experiments}

    def _group_assignments(self, assignments) -> dict[str, dict[str, list]]:
        grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for assignment in assignments:
            grouped[assignment.experiment_key][assignment.variant].append(assignment)
        return grouped

    def _group_events_by_user(self, events) -> dict[int, list]:
        grouped: dict[int, list] = defaultdict(list)
        for event in events:
            grouped[event.user_id].append(event)
        for user_id in grouped:
            grouped[user_id].sort(key=lambda item: item.created_at)
        return grouped

    def _variant_metrics(self, *, experiment_key: str, variant: str, assignments, user_events: dict[int, list]) -> dict:
        user_count = len(assignments)
        retained = 0
        converted = 0
        total_sessions = 0
        total_messages = 0
        total_learning_actions = 0

        for assignment in assignments:
            events = [
                event for event in user_events.get(assignment.user_id, [])
                if getattr(event, "created_at", None) is not None and event.created_at >= assignment.assigned_at
            ]
            if any(
                event.event_type == "session_started"
                and event.created_at >= assignment.assigned_at + timedelta(days=1)
                for event in events
            ):
                retained += 1
            if any(event.event_type in {"upgrade_completed", "subscription_upgraded"} for event in events):
                converted += 1
            total_sessions += sum(1 for event in events if event.event_type == "session_started")
            total_messages += sum(1 for event in events if event.event_type == "message_sent")
            total_learning_actions += sum(
                1 for event in events if event.event_type in {"lesson_completed", "review_completed"}
            )

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

    def _comparisons(self, variants: list[dict]) -> list[dict]:
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
                    "retention_significance": self._basic_significance(
                        base["_retained"],
                        base["users"],
                        candidate["_retained"],
                        candidate["users"],
                    ),
                    "conversion_significance": self._basic_significance(
                        base["_converted"],
                        base["users"],
                        candidate["_converted"],
                        candidate["users"],
                    ),
                }
            )
        return comparisons

    def _public_variant(self, variant: dict) -> dict:
        return {
            "experiment_key": variant["experiment_key"],
            "variant": variant["variant"],
            "users": variant["users"],
            "retention_rate": variant["retention_rate"],
            "conversion_rate": variant["conversion_rate"],
            "engagement": variant["engagement"],
        }

    def _basic_significance(self, success_a: int, total_a: int, success_b: int, total_b: int) -> dict:
        if total_a <= 0 or total_b <= 0:
            return {"z_score": 0.0, "is_significant": False}
        p_a = success_a / total_a
        p_b = success_b / total_b
        pooled = (success_a + success_b) / (total_a + total_b)
        variance = pooled * (1 - pooled) * ((1 / total_a) + (1 / total_b))
        if variance <= 0:
            return {"z_score": 0.0, "is_significant": False}
        z_score = (p_b - p_a) / math.sqrt(variance)
        return {
            "z_score": round(z_score, 3),
            "is_significant": abs(z_score) >= 1.96,
        }
