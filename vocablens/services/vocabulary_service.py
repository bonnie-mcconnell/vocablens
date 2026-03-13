from datetime import datetime
from typing import List

from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import NotFoundError
from vocablens.services.spaced_repetition_service import SpacedRepetitionService

from vocablens.providers.translation.base import Translator
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.services.word_extraction_service import WordExtractionService
from vocablens.services.language_detection_service import LanguageDetectionService
from vocablens.services.difficulty_service import DifficultyService

from vocablens.tasks.enrichment_tasks import enrich_vocabulary_item


class VocabularyService:

    def __init__(
        self,
        translator: Translator,
        repository: SQLiteVocabularyRepository,
        extractor: WordExtractionService,
    ):

        self._translator = translator
        self._repository = repository
        self._extractor = extractor

        self._srs = SpacedRepetitionService()
        self._lang_detector = LanguageDetectionService()
        self._difficulty = DifficultyService()

    # ------------------------------------------------
    # SINGLE WORD
    # ------------------------------------------------

    def process_text(
        self,
        user_id: int,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> VocabularyItem:

        if source_lang == "auto":
            source_lang = self._lang_detector.detect(text)

        translated = self._translator.translate(
            text,
            source_lang,
            target_lang,
        )

        difficulty = self._difficulty.score(text)

        item = VocabularyItem(
            id=None,
            source_text=text,
            translated_text=translated,
            source_lang=source_lang,
            target_lang=target_lang,
            created_at=datetime.utcnow(),
            ease_factor=2.5,
            interval=1,
            repetitions=0,
        )

        saved = self._repository.add(user_id, item)

        # async enrichment
        enrich_vocabulary_item.delay(
            saved.id,
            saved.source_text,
            saved.source_lang,
            saved.target_lang,
        )

        return saved

    # ------------------------------------------------
    # OCR PIPELINE
    # ------------------------------------------------

    def process_ocr_text(
        self,
        user_id: int,
        text: str,
        source_lang: str | None,
        target_lang: str,
    ):

        if not source_lang:
            source_lang = self._lang_detector.detect(text)

        words = self._extractor.extract_words(text)

        return self.process_vocabulary_batch(
            user_id,
            words,
            source_lang,
            target_lang,
        )

    # ------------------------------------------------
    # BATCH
    # ------------------------------------------------

    def process_vocabulary_batch(
        self,
        user_id: int,
        words: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[VocabularyItem]:

        translations = self._translator.translate_batch(
            words,
            source_lang,
            target_lang,
        )

        items = []

        for i, word in enumerate(words):

            if self._repository.exists(
                user_id,
                word,
                source_lang,
                target_lang,
            ):
                continue

            difficulty = self._difficulty.score(word)

            item = VocabularyItem(
                id=None,
                source_text=word,
                translated_text=translations[i],
                source_lang=source_lang,
                target_lang=target_lang,
            created_at=datetime.utcnow(),
            ease_factor=2.5,
            interval=1,
            repetitions=0,
        )

            saved = self._repository.add(user_id, item)

            enrich_vocabulary_item.delay(
                saved.id,
                saved.source_text,
                saved.source_lang,
                saved.target_lang,
            )

            items.append(saved)

        return items

    # ------------------------------------------------
    # REVIEW
    # ------------------------------------------------

    def review_item(
        self,
        user_id: int,
        item_id: int,
        rating: str,
    ) -> VocabularyItem:

        item = self._repository.get(user_id, item_id)

        if not item:
            raise NotFoundError(
                f"Vocabulary item {item_id} not found"
            )

        quality_map = {
            "again": 2,
            "hard": 3,
            "good": 4,
            "easy": 5,
        }

        quality = quality_map.get(rating, 3)

        updated = self._srs.review(item, quality)

        return self._repository.update(updated)

    def review_session(
        self,
        user_id: int,
        limit: int = 10,
    ) -> List[VocabularyItem]:

        items = self._repository.list_due(user_id)

        return items[:limit]
