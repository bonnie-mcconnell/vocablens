from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.services.spaced_repetition_service import SpacedRepetitionService


class RetentionProcessor:
    """
    Adjusts retention scheduling based on review events.
    """

    SUPPORTED = {"word_reviewed"}

    def __init__(
        self,
        retention: RetentionEngine,
        repo: SQLiteVocabularyRepository,
    ):
        self._retention = retention
        self._repo = repo
        self._srs = SpacedRepetitionService()

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    def handle(self, event_type: str, user_id: int, payload: dict) -> None:

        if event_type != "word_reviewed":
            return

        item_id = payload.get("item_id")
        if item_id is None:
            return

        item = self._repo.get(user_id, item_id)
        if not item:
            return

        quality = payload.get("quality")
        if quality is None:
            return

        updated = self._srs.review(item, int(quality))
        self._repo.update(updated)
