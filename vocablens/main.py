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
from vocablens.domain.errors import TranslationError, PersistenceError

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("vocablens")


# ------------------------------------------------------------------
# App Factory
# ------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="VocabLens API")

    db_path = Path("vocablens.db")

    # Infrastructure
    translator = LibreTranslateProvider()
    vocab_repo = SQLiteVocabularyRepository(db_path)
    user_repo = SQLiteUserRepository(db_path)

    # Services
    vocab_service = VocabularyService(translator, vocab_repo)
    ocr_provider = PyTesseractProvider()
    ocr_service = OCRService(ocr_provider)

    # -------------------------
    # Startup / Shutdown
    # -------------------------

    @app.on_event("startup")
    async def startup():
        init_db(db_path)
        logger.info("Database initialized")

    @app.on_event("shutdown")
    async def shutdown():
        translator.close()
        logger.info("Application shutdown complete")

    # -------------------------
    # Routers
    # -------------------------

    app.include_router(
        create_routes(
            service=vocab_service,          # MUST match signature
            ocr_service=ocr_service,
            user_repo=user_repo,
        )
    )

    # -------------------------
    # Middleware
    # -------------------------

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info("Request: %s %s", request.method, request.url.path)
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

    return app


app = create_app()