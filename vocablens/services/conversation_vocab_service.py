from typing import List

from vocablens.services.word_extraction_service import WordExtractionService
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.infrastructure.unit_of_work import UnitOfWork


class ConversationVocabularyService:
    """
    Extracts new vocabulary from user conversation
    and adds it to their vocabulary list.
    """

    def __init__(
        self,
        extractor: WordExtractionService,
        vocab_service: VocabularyService,
        uow_factory: type[UnitOfWork],
    ):
        self._extractor = extractor
        self._vocab_service = vocab_service
        self._uow_factory = uow_factory

    async def process_message(
        self,
        user_id: int,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> List[str]:

        words = self._extractor.extract_words(text)

        async with self._uow_factory() as uow:
            known_words = {
                item.source_text
                for item in await uow.vocab.list_all(user_id, limit=1000, offset=0)
            }

        new_words = []

        for word in words:

            if word in known_words:
                continue

            try:

                await self._vocab_service.process_text(
                    user_id=user_id,
                    text=word,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )

                new_words.append(word)

            except Exception:
                # ignore translation failures etc
                pass

        return new_words
