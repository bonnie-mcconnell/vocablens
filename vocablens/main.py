from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.providers.translation.http_provider import HTTPTranslationProvider
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.api.routes import create_routes
from vocablens.domain.errors import TranslationError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

DB_PATH = Path("vocablens.db")

init_db(DB_PATH)

translator = HTTPTranslationProvider()
repository = SQLiteVocabularyRepository(DB_PATH)

ocr_provider = PyTesseractProvider()
ocr_service = OCRService(ocr_provider)

vocab_service = VocabularyService(translator, repository)

app = FastAPI(title="VocabLens")

app.include_router(create_routes(vocab_service, ocr_service))


@app.exception_handler(TranslationError)
async def translation_exception_handler(request: Request, exc: TranslationError):
    return JSONResponse(
        status_code=502,
        content={"detail": "Translation service unavailable"},
    )