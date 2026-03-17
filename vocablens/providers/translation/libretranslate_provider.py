import httpx
import logging
from typing import List, Optional
import asyncio
import time

import anyio

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
        self._client = httpx.AsyncClient(timeout=timeout)
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

        return self._run_async(
            self._translate_async(text=text, source_lang=source_lang, target_lang=target_lang)
        )

    # ------------------------------------------------
    # Batch translation
    # ------------------------------------------------

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:

        return self._run_async(
            self._translate_batch_async(texts=texts, source_lang=source_lang, target_lang=target_lang)
        )

    def close(self):
        self._run_async(self._client.aclose())

    def _run_async(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return anyio.run(lambda: coro)

        if loop.is_running():
            return anyio.from_thread.run(lambda: coro)

        return loop.run_until_complete(coro)  # pragma: no cover

    async def _translate_async(self, text: str, source_lang: str, target_lang: str) -> str:
        cache_key = f"lt:{source_lang}:{target_lang}:{text}"
        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                CACHE_HITS.labels(cache="translation", op="get").inc()
                return cached
            CACHE_MISSES.labels(cache="translation", op="get").inc()

        try:
            start = time.perf_counter()
            response = await self._client.post(
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
                await self._cache.set(cache_key, translated, ttl=int(settings.TRANSLATE_TIMEOUT))

            return translated

        except httpx.RequestError as exc:
            raise TranslationError("Translation request failed") from exc

        except httpx.HTTPStatusError as exc:
            raise TranslationError(
                f"Translation service error: {exc.response.status_code}"
            ) from exc

    async def _translate_batch_async(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:

        results: List[Optional[str]] = [None] * len(texts)
        missing: List[tuple[int, str]] = []

        if self._cache:
            for idx, t in enumerate(texts):
                ck = f"lt:{source_lang}:{target_lang}:{t}"
                cached = await self._cache.get(ck)
                if cached is not None:
                    results[idx] = cached
                else:
                    missing.append((idx, t))
            if not missing:
                return [r for r in results if r is not None]

        for idx, text in missing or list(enumerate(texts)):
            translated = await self._translate_async(text, source_lang, target_lang)
            results[idx] = translated

        return [r for r in results if r is not None]
