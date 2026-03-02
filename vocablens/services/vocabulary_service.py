from datetime import datetime

from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import NotFoundError
from vocablens.providers.translation.base import Translator
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository


class VocabularyService:
    def __init__(
        self,
        translator: Translator,
        repository: SQLiteVocabularyRepository,
    ) -> None:
        self._translator = translator
        self._repository = repository

    def process_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> VocabularyItem:

        translated = self._translator.translate(text, target_lang)

        item = VocabularyItem(
            id=None,
            source_text=text,
            translated_text=translated,
            source_lang=source_lang,
            target_lang=target_lang,
            created_at=datetime.utcnow(),
        )

        return self._repository.add(item)

    def list_vocabulary(self) -> list[VocabularyItem]:
        return self._repository.list_all()

    def review_item(self, item_id: int) -> VocabularyItem:
        try:
            return self._repository.increment_review(item_id)
        except ValueError:
            raise NotFoundError(f"Vocabulary item {item_id} not found")