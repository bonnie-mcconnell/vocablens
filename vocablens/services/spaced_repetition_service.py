import math
from dataclasses import dataclass
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.domain.models import VocabularyItem


@dataclass(frozen=True)
class ReviewSchedule:
    next_review_at: object
    interval_days: float
    stability_days: float
    recall_probability: float


class SpacedRepetitionService:
    """
    Forgetting-curve scheduler with difficulty and personalization inputs.
    """

    def initialize(
        self,
        item: VocabularyItem,
        *,
        retention_rate: float = 0.8,
        difficulty_score: float = 0.5,
        review_frequency_multiplier: float = 1.0,
    ) -> VocabularyItem:
        schedule = self.schedule(
            item,
            retention_rate=retention_rate,
            mistake_frequency=0,
            response_accuracy=0.65,
            difficulty_score=difficulty_score,
            review_frequency_multiplier=review_frequency_multiplier,
        )
        item.next_review_due = schedule.next_review_at
        item.interval = max(1, int(round(schedule.interval_days)))
        return item

    def review(
        self,
        item: VocabularyItem,
        quality: int,
        *,
        retention_rate: float = 0.8,
        mistake_frequency: int = 0,
        difficulty_score: float = 0.5,
        review_frequency_multiplier: float = 1.0,
    ) -> VocabularyItem:
        quality = max(0, min(5, quality))
        response_accuracy = quality / 5.0
        now = utc_now()

        if quality <= 2:
            item.repetitions = 0
        else:
            item.repetitions += 1

        ease_delta = (
            (response_accuracy - 0.6) * 0.35
            - (min(mistake_frequency, 8) * 0.03)
            - (difficulty_score * 0.08)
        )
        if quality <= 2:
            ease_delta -= 0.18
        else:
            ease_delta += 0.04
        item.ease_factor = min(3.2, max(1.15, item.ease_factor + ease_delta))

        schedule = self.schedule(
            item,
            retention_rate=retention_rate,
            mistake_frequency=mistake_frequency,
            response_accuracy=response_accuracy,
            difficulty_score=difficulty_score,
            review_frequency_multiplier=review_frequency_multiplier,
        )
        item.last_reviewed_at = now
        item.next_review_due = schedule.next_review_at
        item.interval = max(1, int(round(schedule.interval_days)))
        item.review_count += 1
        return item

    def schedule(
        self,
        item: VocabularyItem,
        *,
        retention_rate: float,
        mistake_frequency: int,
        response_accuracy: float,
        difficulty_score: float,
        review_frequency_multiplier: float,
    ) -> ReviewSchedule:
        now = utc_now()
        response_accuracy = max(0.0, min(1.0, response_accuracy))
        difficulty_score = max(0.0, min(1.0, difficulty_score))
        retention_rate = max(0.3, min(1.0, retention_rate))
        review_frequency_multiplier = max(0.6, min(1.4, review_frequency_multiplier))

        stability_days = self._memory_stability(
            item,
            retention_rate=retention_rate,
            mistake_frequency=mistake_frequency,
            response_accuracy=response_accuracy,
            difficulty_score=difficulty_score,
        )
        interval_days = max(
            0.2,
            min(
                365.0,
                stability_days
                * (0.55 + (response_accuracy * 0.95))
                * review_frequency_multiplier,
            ),
        )
        if response_accuracy <= 0.4:
            interval_days = min(interval_days, 0.5)

        return ReviewSchedule(
            next_review_at=now + timedelta(days=interval_days),
            interval_days=interval_days,
            stability_days=stability_days,
            recall_probability=self.recall_probability(
                item,
                retention_rate=retention_rate,
                mistake_frequency=mistake_frequency,
                difficulty_score=difficulty_score,
                as_of=now,
            ),
        )

    def recall_probability(
        self,
        item: VocabularyItem,
        *,
        retention_rate: float,
        mistake_frequency: int,
        difficulty_score: float,
        as_of=None,
    ) -> float:
        as_of = as_of or utc_now()
        anchor = getattr(item, "last_reviewed_at", None) or getattr(item, "created_at", None)
        if anchor is None:
            next_due = getattr(item, "next_review_due", None)
            interval_days = max(1.0, float(getattr(item, "interval", 1) or 1))
            anchor = next_due - timedelta(days=interval_days) if next_due is not None else as_of
        elapsed_days = max(0.0, (as_of - anchor).total_seconds() / 86400)
        stability_days = self._memory_stability(
            item,
            retention_rate=retention_rate,
            mistake_frequency=mistake_frequency,
            response_accuracy=0.7,
            difficulty_score=difficulty_score,
        )
        probability = math.exp(-(elapsed_days / max(stability_days, 0.1)))
        return max(0.0, min(1.0, probability))

    def _memory_stability(
        self,
        item: VocabularyItem,
        *,
        retention_rate: float,
        mistake_frequency: int,
        response_accuracy: float,
        difficulty_score: float,
    ) -> float:
        base_interval = max(0.5, float(getattr(item, "interval", 1) or 1))
        ease = max(1.15, float(getattr(item, "ease_factor", 2.5) or 2.5))
        repetitions = max(0, int(getattr(item, "repetitions", 0) or 0))
        base = base_interval * (0.8 + (ease / 2.0))
        repetition_bonus = 1.0 + min(repetitions, 10) * 0.18
        retention_modifier = 0.7 + (retention_rate * 0.85)
        difficulty_modifier = max(0.55, 1.2 - (difficulty_score * 0.6))
        mistake_modifier = max(0.4, 1.0 - (min(mistake_frequency, 10) * 0.08))
        accuracy_modifier = 0.65 + (response_accuracy * 0.95)
        return max(
            0.2,
            base
            * repetition_bonus
            * retention_modifier
            * difficulty_modifier
            * mistake_modifier
            * accuracy_modifier,
        )
