from datetime import datetime


class RetentionEngine:
    """
    Legacy shim retained for compatibility.
    Review scheduling now handled by SpacedRepetitionService.
    """

    def needs_review(self, item):
        return bool(
            item.next_review_due
            and item.next_review_due <= datetime.utcnow()
        )

    def review_load(self, items):
        return len([i for i in items if self.needs_review(i)])
