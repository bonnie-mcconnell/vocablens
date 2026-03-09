import io
from PIL import Image
import pytesseract

from vocablens.domain.errors import OCRProcessingError


class PyTesseractProvider:
    """
    OCR provider using Tesseract.
    """

    def extract_text(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))

            text = pytesseract.image_to_string(image)

            return text.strip()

        except Exception as exc:
            raise OCRProcessingError(
                f"OCR extraction failed: {exc}"
            ) from exc