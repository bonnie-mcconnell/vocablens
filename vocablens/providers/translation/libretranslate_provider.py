import httpx
import logging
from typing import List
import asyncio
import time

from vocablens.infrastructure.observability.metrics import CACHE_HITS, CACHE_MISSES, REQUEST_LATENCY

from vocablens.providers.translation.base import Translator
from vocablens.domain.errors import TranslationError
from vocablens.config.settings import settings
from vocablens.infrastructure.cache.redis_cache import get_cache_backend

logger = logging.getLogger(__name__)


class LibreTranslateProvider(Translator):

    def __init__(
        self,
        base_url: str = "https://libretranslate.com",
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._cache = get_cache_backend() if settings.ENABLE_REDIS_CACHE else None

    # ------------------------------------------------
    # Single translation
    # ------------------------------------------------

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:

        cache_key = f"lt:{source_lang}:{target_lang}:{text}"
        if self._cache:
            cached = asyncio.run(self._cache.get(cache_key))
            if cached:
                CACHE_HITS.labels(cache="translation", op="get").inc()
                return cached
            CACHE_MISSES.labels(cache="translation", op="get").inc()

        try:
            start = time.perf_counter()
            response = self._client.post(
                f"{self._base_url}/translate",
                json={
                    "q": text,
                    "source": source_lang,
                    "target": target_lang,
                    "format": "text",
                },
            )
            REQUEST_LATENCY.labels(method="POST", endpoint="/translate", status=response.status_code).observe(
                time.perf_counter() - start
            )

            response.raise_for_status()

            data = response.json()

            translated = data.get("translatedText")

            if not translated:
                raise TranslationError("Malformed translation response")

            if self._cache:
                asyncio.run(self._cache.set(cache_key, translated, ttl=int(settings.TRANSLATE_TIMEOUT)))

            return translated

        except httpx.RequestError as exc:
            raise TranslationError("Translation request failed") from exc

        except httpx.HTTPStatusError as exc:
            raise TranslationError(
                f"Translation service error: {exc.response.status_code}"
            ) from exc

    # ------------------------------------------------
    # Batch translation
    # ------------------------------------------------

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:

        if self._cache:
            results = []
            missing = []
            for t in texts:
                ck = f"lt:{source_lang}:{target_lang}:{t}"
                cached = asyncio.run(self._cache.get(ck))
                if cached:
                    results.append(cached)
                else:
                    results.append(None)
                    missing.append(t)
            if not missing:
                return results  # all cached
            texts = missing

        translations = []

        for text in texts:
            translated = self.translate(
                text,
                source_lang,
                target_lang,
            )
            translations.append(translated)

        return translations

    def close(self):
        self._client.close()
