from vocablens.services.retention_engine import RetentionEngine


class ReviewService:

    def __init__(self, retention_engine, vocab_repo):
        self.retention = retention_engine
        self.repo = vocab_repo

    def get_review_items(self, user_id):

        items = self.repo.list_all(user_id, limit=1000, offset=0)

        review_items = []

        for item in items:

            if self.retention.needs_review(item):

                review_items.append(item)

        return review_items