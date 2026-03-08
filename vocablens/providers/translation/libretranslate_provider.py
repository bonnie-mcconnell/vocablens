import httpx
import logging
from typing import List

from vocablens.providers.translation.base import Translator
from vocablens.domain.errors import TranslationError

logger = logging.getLogger(__name__)


class LibreTranslateProvider(Translator):

    def __init__(
        self,
        base_url: str = "https://libretranslate.com",
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------
    # Single translation
    # ------------------------------------------------

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:

        try:

            response = self._client.post(
                f"{self._base_url}/translate",
                json={
                    "q": text,
                    "source": source_lang,
                    "target": target_lang,
                    "format": "text",
                },
            )

            response.raise_for_status()

            data = response.json()

            translated = data.get("translatedText")

            if not translated:
                raise TranslationError("Malformed translation response")

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