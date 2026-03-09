from typing import Protocol


class OCRProvider(Protocol):
    """
    OCR provider interface.
    Implementations must provide text extraction from image bytes.
    """

    def extract_text(self, image_bytes: bytes) -> str:
        ...