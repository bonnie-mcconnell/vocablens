import httpx
from vocablens.providers.translation.base import Translator
from vocablens.domain.errors import TranslationError


class LibreTranslateProvider(Translator):
    def __init__(
        self,
        base_url: str = "https://libretranslate.com",
        timeout: float = 5.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def translate(self, text: str, target_lang: str) -> str:
        try:
            response = self._client.post(
                f"{self._base_url}/translate",
                json={
                    "q": text,
                    "source": "auto",
                    "target": target_lang,
                    "format": "text",
                },
            )

            response.raise_for_status()

            data = response.json()

            if "translatedText" not in data:
                raise TranslationError("Malformed translation response")

            return data["translatedText"]

        except httpx.RequestError as exc:
            raise TranslationError("Translation request failed") from exc

        except httpx.HTTPStatusError as exc:
            raise TranslationError(
                f"Translation service error: {exc.response.status_code}"
            ) from exc

    def close(self):
        self._client.close()