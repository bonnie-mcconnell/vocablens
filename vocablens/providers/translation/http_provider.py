import httpx
from vocablens.domain.errors import TranslationError


class HTTPTranslationProvider:
    def __init__(self, base_url: str = "https://libretranslate.com"):
        self._base_url = base_url

    def translate(self, text: str, target_lang: str) -> str:
        try:
            response = httpx.post(
                f"{self._base_url}/translate",
                json={
                    "q": text,
                    "source": "auto",
                    "target": target_lang,
                    "format": "text",
                },
                timeout=5.0,
            )
            response.raise_for_status()
            return response.json()["translatedText"]
        except Exception as exc:
            raise TranslationError(str(exc)) from exc