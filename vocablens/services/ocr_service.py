from vocablens.providers.ocr.base import OCRProvider


class OCRService:
    def __init__(self, provider: OCRProvider):
        self._provider = provider

    def extract(self, image_bytes: bytes) -> str:
        return self._provider.extract_text(image_bytes)