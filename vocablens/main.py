from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.infrastructure.repositories_users import SQLiteUserRepository
from vocablens.providers.translation.libretranslate_provider import LibreTranslateProvider
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.api.routes import create_routes
from vocablens.domain.errors import (
    TranslationError,
    PersistenceError,
)

# -------------------------
# Logging
# -------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

# -------------------------
# Configuration
# -------------------------

DB_PATH = Path("vocablens.db")

# -------------------------
# App Factory
# -------------------------

def create_app() -> FastAPI:

    init_db(DB_PATH)

    translator = LibreTranslateProvider()
    vocab_repo = SQLiteVocabularyRepository(DB_PATH)
    user_repo = SQLiteUserRepository(DB_PATH)

    ocr_provider = PyTesseractProvider()
    ocr_service = OCRService(ocr_provider)

    vocab_service = VocabularyService(translator, vocab_repo)

    app = FastAPI(title="VocabLens API")

    # Routers
    app.include_router(
        create_routes(
            vocab_service,
            ocr_service,
            user_repo,
        )
    )

    # -------------------------
    # Middleware
    # -------------------------

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info("Request: %s %s", request.method, request.url)
        response = await call_next(request)
        logger.info("Response: %s", response.status_code)
        return response

    # -------------------------
    # Exception Handlers
    # -------------------------

    @app.exception_handler(TranslationError)
    async def translation_handler(request: Request, exc: TranslationError):
        return JSONResponse(
            status_code=502,
            content={"detail": "Translation service unavailable"},
        )

    @app.exception_handler(PersistenceError)
    async def persistence_handler(request: Request, exc: PersistenceError):
        return JSONResponse(
            status_code=500,
            content={"detail": "Database error"},
        )

    # Graceful shutdown
    @app.on_event("shutdown")
    def shutdown_event():
        translator.close()

    return app


app = create_app()