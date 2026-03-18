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
        retention_rate, review_multiplier = await self._schedule_profile(user_id)

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
        item = self._srs.initialize(
            item,
            retention_rate=retention_rate,
            difficulty_score=difficulty,
            review_frequency_multiplier=review_multiplier,
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
        retention_rate, review_multiplier = await self._schedule_profile(user_id)

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
            item = self._srs.initialize(
                item,
                retention_rate=retention_rate,
                difficulty_score=difficulty,
                review_frequency_multiplier=review_multiplier,
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
            profile = await uow.profiles.get_or_create(user_id)
            patterns = await uow.mistake_patterns.top_patterns(user_id, limit=20)

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
        response_accuracy = quality / 5.0
        difficulty_score = self._difficulty.score(item.source_text)
        mistake_frequency = self._mistake_frequency(item.source_text, patterns)
        review_multiplier = self._review_multiplier(profile)

        updated = self._srs.review(
            item,
            quality,
            retention_rate=profile.retention_rate,
            mistake_frequency=mistake_frequency,
            difficulty_score=difficulty_score,
            review_frequency_multiplier=review_multiplier,
        )

        async with self._uow_factory() as uow:
            updated_item = await uow.vocab.update(updated)
            await uow.commit()

        if self._events:
            await self._events.record(
                "word_reviewed",
                user_id,
                {
                    "item_id": updated_item.id,
                    "quality": quality,
                    "response_accuracy": response_accuracy,
                },
            )

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

    async def _schedule_profile(self, user_id: int) -> tuple[float, float]:
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            return profile.retention_rate, self._review_multiplier(profile)

    def _review_multiplier(self, profile) -> float:
        preference = (getattr(profile, "difficulty_preference", "medium") or "medium").lower()
        if preference == "easy":
            return 0.9
        if preference == "hard":
            return 1.1
        return 1.0

    def _mistake_frequency(self, source_text: str, patterns) -> int:
        word = source_text.lower()
        frequency = 0
        for pattern in patterns or []:
            text = getattr(pattern, "pattern", "")
            if word in str(text).lower():
                frequency += int(getattr(pattern, "count", 1) or 1)
        return frequency
