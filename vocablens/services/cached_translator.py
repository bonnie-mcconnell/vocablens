import logging
from typing import List

from vocablens.providers.translation.base import Translator

logger = logging.getLogger(__name__)


class CachedTranslator:

    def __init__(self, provider: Translator, cache_repo):
        self.provider = provider
        self.cache_repo = cache_repo

    # -----------------------------------------
    # Single translation
    # -----------------------------------------

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:

        cached = self.cache_repo.get_sync(text, source_lang, target_lang)

        if cached:
            logger.debug("Translation cache hit")
            return cached

        logger.debug("Translation cache miss")

        result = self.provider.translate(
            text,
            source_lang,
            target_lang,
        )

        self.cache_repo.save_sync(
            text,
            source_lang,
            target_lang,
            result,
        )

        return result

    # -----------------------------------------
    # Batch translation
    # -----------------------------------------

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:

        results = []
        missing = []
        missing_indexes = []

        for i, text in enumerate(texts):

            cached = self.cache_repo.get_sync(
                text,
                source_lang,
                target_lang,
            )

            if cached:
                results.append(cached)
            else:
                results.append(None)
                missing.append(text)
                missing_indexes.append(i)

        if missing:

            translations = self.provider.translate_batch(
                missing,
                source_lang,
                target_lang,
            )

            for idx, text, translation in zip(
                missing_indexes,
                missing,
                translations,
            ):
                results[idx] = translation

                self.cache_repo.save_sync(
                    text,
                    source_lang,
                    target_lang,
                    translation,
                )

        return results

    def close(self):
        if hasattr(self.provider, "close"):
            self.provider.close()
