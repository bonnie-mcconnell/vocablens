from datetime import datetime, timedelta

from vocablens.domain.models import VocabularyItem


class SpacedRepetitionService:
    """
    SM-2 spaced repetition scheduler.
    """

    def review(self, item: VocabularyItem, quality: int) -> VocabularyItem:
        # quality expected 0–5
        quality = max(0, min(5, quality))

        if quality < 3:
            item.repetitions = 0
            item.interval = 1
        else:
            if item.repetitions == 0:
                item.interval = 1
            elif item.repetitions == 1:
                item.interval = 6
            else:
                item.interval = int(round(item.interval * item.ease_factor))

            item.repetitions += 1

        # ease factor update
        item.ease_factor = item.ease_factor + (
            0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        )
        item.ease_factor = max(1.3, item.ease_factor)

        now = datetime.utcnow()
        item.last_reviewed_at = now
        item.next_review_due = now + timedelta(days=item.interval)
        item.review_count += 1

        return item
