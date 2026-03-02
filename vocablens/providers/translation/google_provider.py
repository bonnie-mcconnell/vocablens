from googletrans import Translator as GoogleTranslator
from vocablens.domain.errors import TranslationError


class GoogleTranslateProvider:
    def __init__(self) -> None:
        self._client = GoogleTranslator()

    def translate(self, text: str, target_lang: str) -> str:
        try:
            result = self._client.translate(text, dest=target_lang)
            return result.text
        except Exception as exc:
            raise TranslationError(str(exc)) from exc