from pathlib import Path
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.infrastructure.repositories_users import SQLiteUserRepository
from vocablens.infrastructure.repositories_translation_cache import (
    SQLiteTranslationCacheRepository,
)

from vocablens.providers.translation.libretranslate_provider import LibreTranslateProvider
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.providers.llm.openai_provider import OpenAIProvider

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.services.cached_translator import CachedTranslator
from vocablens.services.word_extraction_service import WordExtractionService

from vocablens.services.example_sentence_service import ExampleSentenceService
from vocablens.services.grammar_service import GrammarExplanationService
from vocablens.services.semantic_cluster_service import SemanticClusterService
from vocablens.services.conversation_service import ConversationService

from vocablens.api.routes import create_routes
from vocablens.api.routers.conversation_router import create_conversation_router

from vocablens.domain.errors import TranslationError, PersistenceError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("vocablens")


def create_app() -> FastAPI:

    app = FastAPI(
        title="VocabLens API",
        version="1.0.0",
    )

    db_path = Path("vocablens.db")

    # ------------------------------------------------
    # Repositories
    # ------------------------------------------------

    vocab_repo = SQLiteVocabularyRepository(db_path)
    user_repo = SQLiteUserRepository(db_path)
    cache_repo = SQLiteTranslationCacheRepository(str(db_path))

    # ------------------------------------------------
    # Providers
    # ------------------------------------------------

    translator_provider = LibreTranslateProvider()
    ocr_provider = PyTesseractProvider()
    llm_provider = OpenAIProvider()

    # ------------------------------------------------
    # Services
    # ------------------------------------------------

    translator = CachedTranslator(
        provider=translator_provider,
        cache_repo=cache_repo,
    )

    extractor = WordExtractionService()

    sentence_service = ExampleSentenceService(llm_provider)
    grammar_service = GrammarExplanationService(llm_provider)
    cluster_service = SemanticClusterService(llm_provider)

    vocab_service = VocabularyService(
        translator,
        vocab_repo,
        extractor,
        sentence_service,
        grammar_service,
        cluster_service,
    )

    conversation_service = ConversationService(
        llm_provider,
        vocab_repo,
    )

    ocr_service = OCRService(ocr_provider)

    # ------------------------------------------------
    # Middleware
    # ------------------------------------------------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):

        start = time.time()

        response = await call_next(request)

        duration = time.time() - start

        logger.info(
            "%s %s -> %s (%.3fs)",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )

        return response

    # ------------------------------------------------
    # Health Endpoint
    # ------------------------------------------------

    @app.get("/health", tags=["System"])
    def health():
        return {"status": "ok"}

    # ------------------------------------------------
    # Startup
    # ------------------------------------------------

    @app.on_event("startup")
    async def startup():
        init_db(db_path)
        logger.info("Database initialized")

    # ------------------------------------------------
    # Routes
    # ------------------------------------------------

    app.include_router(
        create_routes(
            service=vocab_service,
            ocr_service=ocr_service,
            user_repo=user_repo,
        )
    )

    app.include_router(
        create_conversation_router(conversation_service)
    )

    # ------------------------------------------------
    # Error Handlers
    # ------------------------------------------------

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