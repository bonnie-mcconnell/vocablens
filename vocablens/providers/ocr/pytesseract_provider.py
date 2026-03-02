import io
from PIL import Image
import pytesseract

from vocablens.domain.errors import OCRProcessingError


class PyTesseractProvider:
    def extract_text(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            return pytesseract.image_to_string(image).strip()
        except Exception as exc:
            raise OCRProcessingError(str(exc)) from exc