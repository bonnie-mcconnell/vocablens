from typing import List

from vocablens.core.time import utc_now
from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import NotFoundError
from vocablens.services.spaced_repetition_service import SpacedRepetitionService

from vocablens.providers.translation.base import Translator
from vocablens.services.word_extraction_service import WordExtractionService
from vocablens.services.language_detection_service import LanguageDetectionService
from vocablens.services.difficulty_service import DifficultyService
from vocablens.services.learning_event_service import LearningEventService


class VocabularyService:

    def __init__(
        self,
        translator: Translator,
        uow_factory,
        extractor: WordExtractionService,
        events: LearningEventService | None = None,
    ):

        self._translator = translator
        self._uow_factory = uow_factory
        self._extractor = extractor
        self._events = events

        self._srs = SpacedRepetitionService()
        self._lang_detector = LanguageDetectionService()
        self._difficulty = DifficultyService()

    # ------------------------------------------------
    # SINGLE WORD
    # ------------------------------------------------

    async def process_text(
        self,
        user_id: int,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> VocabularyItem:

        if source_lang == "auto":
            source_lang = self._lang_detector.detect(text)

        translated = await self._translator.translate(
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
            created_at=utc_now(),
            ease_factor=2.5,
            interval=1,
            repetitions=0,
        )

        async with self._uow_factory() as uow:
            saved = await uow.vocab.add(user_id, item)
            await uow.commit()

        if self._events:
            await self._events.record(
                "word_learned",
                user_id,
                {
                    "words": [saved.source_text],
                    "item_id": saved.id,
                    "source_text": saved.source_text,
                    "source_lang": saved.source_lang,
                    "target_lang": saved.target_lang,
                },
            )

        return saved

    # ------------------------------------------------
    # OCR PIPELINE
    # ------------------------------------------------

    async def process_ocr_text(
        self,
        user_id: int,
        text: str,
        source_lang: str | None,
        target_lang: str,
    ):

        if not source_lang:
            source_lang = self._lang_detector.detect(text)

        words = self._extractor.extract_words(text)

        return await self.process_vocabulary_batch(
            user_id,
            words,
            source_lang,
            target_lang,
        )

    # ------------------------------------------------
    # BATCH
    # ------------------------------------------------

    async def process_vocabulary_batch(
        self,
        user_id: int,
        words: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[VocabularyItem]:

        translations = await self._translator.translate_batch(
            words,
            source_lang,
            target_lang,
        )

        items = []

        for i, word in enumerate(words):

            async with self._uow_factory() as uow:
                if await uow.vocab.exists(
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
                created_at=utc_now(),
                ease_factor=2.5,
                interval=1,
                repetitions=0,
            )

            async with self._uow_factory() as uow:
                saved = await uow.vocab.add(user_id, item)
                await uow.commit()

            if self._events and saved:
                await self._events.record(
                    "word_learned",
                    user_id,
                    {
                        "words": [saved.source_text],
                        "item_id": saved.id,
                        "source_text": saved.source_text,
                        "source_lang": saved.source_lang,
                        "target_lang": saved.target_lang,
                    },
                )

            items.append(saved)

        return items

    # ------------------------------------------------
    # REVIEW
    # ------------------------------------------------

    async def review_item(
        self,
        user_id: int,
        item_id: int,
        rating: str,
    ) -> VocabularyItem:

        async with self._uow_factory() as uow:
            item = await uow.vocab.get(user_id, item_id)

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

        async with self._uow_factory() as uow:
            updated_item = await uow.vocab.update(updated)
            await uow.commit()

        return updated_item

    async def review_session(
        self,
        user_id: int,
        limit: int = 10,
    ) -> List[VocabularyItem]:

        async with self._uow_factory() as uow:
            items = await uow.vocab.list_due(user_id)

        return items[:limit]

    # ------------------------------------------------
    # LISTING
    # ------------------------------------------------

    async def list_vocabulary(self, user_id: int, limit: int, offset: int) -> List[VocabularyItem]:
        async with self._uow_factory() as uow:
            return await uow.vocab.list_all(user_id, limit, offset)

    async def list_due_items(self, user_id: int) -> List[VocabularyItem]:
        async with self._uow_factory() as uow:
            return await uow.vocab.list_due(user_id)
