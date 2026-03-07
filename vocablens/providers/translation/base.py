from typing import Protocol


class Translator(Protocol):
    def translate(self, text: str, target_lang: str) -> str:
        ...

    def close(self) -> None:
        ...