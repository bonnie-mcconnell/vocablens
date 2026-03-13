from datetime import datetime


class RetentionEngine:
    """
    Simple forgetting curve model.
    """

    def forgetting_probability(self, item):

        if not item.last_reviewed_at:
            return 0.8

        days = (datetime.utcnow() - item.last_reviewed_at).days

        score = getattr(item, "retention_score", 0.5)

        probability = min(1.0, (days / 7) * (1 - score))

        return probability

    def needs_review(self, item):

        return self.forgetting_probability(item) > 0.6

    def review_load(self, items):

        review_items = [
            item for item in items if self.needs_review(item)
        ]

        return min(len(review_items), 25)