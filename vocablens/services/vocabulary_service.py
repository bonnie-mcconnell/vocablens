from datetime import datetime

from vocablens.domain.models import VocabularyItem
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
            last_reviewed_at=None,
            review_count=0,
        )

        return self._repository.add(item)