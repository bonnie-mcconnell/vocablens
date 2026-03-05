from typing import Protocol


class OCRProvider(Protocol):
    def extract_text(self, image_bytes: bytes) -> str:
        ...


