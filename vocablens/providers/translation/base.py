from typing import Protocol, List


class Translator(Protocol):

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        ...

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        ...

    def close(self) -> None:
        ...