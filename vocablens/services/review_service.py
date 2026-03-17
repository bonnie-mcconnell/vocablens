from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository


class ReviewService:
    """
    Determines which vocabulary items should be reviewed
    based on the forgetting curve.
    """

    def __init__(
        self,
        vocab_repo: PostgresVocabularyRepository,
        retention_engine: RetentionEngine,
    ):
        self._repo = vocab_repo
        self._engine = retention_engine

    def due_reviews(self, user_id: int):

        items = self._repo.list_all_sync(user_id, limit=1000, offset=0)

        return [
            item
            for item in items
            if self._engine.needs_review(item)
        ]
