from pathlib import Path

from fastapi import FastAPI
from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.providers.translation.google_provider import GoogleTranslateProvider
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.routes import create_routes
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.services.ocr_service import OCRService


ocr_provider = PyTesseractProvider()
ocr_service = OCRService(ocr_provider)

DB_PATH = Path("vocablens.db")

init_db(DB_PATH)

translator = GoogleTranslateProvider()
repository = SQLiteVocabularyRepository(DB_PATH)
service = VocabularyService(translator, repository)

app = FastAPI(title="VocabLens")

app.include_router(create_routes(service))