from dataclasses import replace
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.domain.models import VocabularyItem
from vocablens.services.spaced_repetition_service import SpacedRepetitionService


def _item(**overrides):
    base = VocabularyItem(
        id=1,
        source_text="bonjour",
        translated_text="hello",
        source_lang="fr",
        target_lang="en",
        created_at=utc_now() - timedelta(days=10),
        last_reviewed_at=utc_now() - timedelta(days=2),
        review_count=3,
        ease_factor=2.1,
        interval=4,
        repetitions=2,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_scheduler_shortens_interval_for_high_mistake_frequency():
    service = SpacedRepetitionService()
    item = _item()

    low_mistake = service.review(
        replace(item),
        4,
        retention_rate=0.8,
        mistake_frequency=0,
        difficulty_score=0.3,
        review_frequency_multiplier=1.0,
    )
    high_mistake = service.review(
        replace(item),
        4,
        retention_rate=0.8,
        mistake_frequency=5,
        difficulty_score=0.3,
        review_frequency_multiplier=1.0,
    )

    assert high_mistake.next_review_due < low_mistake.next_review_due


def test_scheduler_extends_interval_for_higher_retention_and_accuracy():
    service = SpacedRepetitionService()
    item = _item()

    lower_retention = service.review(
        replace(item),
        3,
        retention_rate=0.55,
        mistake_frequency=0,
        difficulty_score=0.3,
        review_frequency_multiplier=0.9,
    )
    higher_retention = service.review(
        replace(item),
        5,
        retention_rate=0.9,
        mistake_frequency=0,
        difficulty_score=0.3,
        review_frequency_multiplier=1.1,
    )

    assert higher_retention.next_review_due > lower_retention.next_review_due
    assert higher_retention.interval >= lower_retention.interval


def test_recall_probability_decays_over_time():
    service = SpacedRepetitionService()
    recent = _item(last_reviewed_at=utc_now() - timedelta(hours=6))
    old = _item(last_reviewed_at=utc_now() - timedelta(days=8))

    recent_probability = service.recall_probability(
        recent,
        retention_rate=0.8,
        mistake_frequency=0,
        difficulty_score=0.3,
    )
    old_probability = service.recall_probability(
        old,
        retention_rate=0.8,
        mistake_frequency=0,
        difficulty_score=0.3,
    )

    assert recent_probability > old_probability
