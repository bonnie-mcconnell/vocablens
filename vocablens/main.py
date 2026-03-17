import time
import uuid
from sqlalchemy import text

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.infrastructure.postgres_translation_cache_repository import (
    PostgresTranslationCacheRepository,
)
from vocablens.infrastructure.postgres_conversation_repository import PostgresConversationRepository
from vocablens.infrastructure.postgres_learning_event_repository import PostgresLearningEventRepository
from vocablens.infrastructure.postgres_skill_tracking_repository import PostgresSkillTrackingRepository
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository
from vocablens.infrastructure.postgres_embedding_repository import PostgresEmbeddingRepository

# Providers
from vocablens.providers.translation.libretranslate_provider import LibreTranslateProvider
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.providers.llm.openai_provider import OpenAIProvider
from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider

# Core services
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.services.cached_translator import CachedTranslator
from vocablens.services.word_extraction_service import WordExtractionService

# Conversation services
from vocablens.services.conversation_service import ConversationService
from vocablens.services.conversation_memory_service import ConversationMemoryService
from vocablens.services.conversation_vocab_service import ConversationVocabularyService

# AI brain
from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.drill_generation_service import DrillGenerationService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.language_brain_service import LanguageBrainService
from vocablens.services.learning_event_service import LearningEventService

# Learning
from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.lesson_generation_service import LessonGenerationService
from vocablens.services.scenario_service import ScenarioService

# Intelligence
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.learning_roadmap_service import LearningRoadmapService
from vocablens.services.retention_engine import RetentionEngine

# Speech
from vocablens.services.speech_conversation_service import SpeechConversationService

# Logging / Observability
from vocablens.infrastructure.logging.logger import setup_logging, get_logger
from vocablens.infrastructure.observability.metrics import REQUEST_LATENCY
from vocablens.infrastructure.rate_limit import RateLimiter
from vocablens.config.settings import settings

# Event processors
from vocablens.services.event_processors.skill_update_processor import SkillUpdateProcessor
from vocablens.services.event_processors.retention_processor import RetentionProcessor
from vocablens.services.event_processors.knowledge_graph_processor import KnowledgeGraphProcessor

# Routes
from vocablens.api.routes import create_routes


setup_logging()
logger = get_logger("vocablens")


def create_app() -> FastAPI:

    app = FastAPI(
        title="VocabLens API",
        version="1.0.0",
    )

    # ---------------------------------------------------
    # Repositories
    # ---------------------------------------------------

    vocab_repo = PostgresVocabularyRepository(AsyncSessionMaker)
    user_repo = PostgresUserRepository(AsyncSessionMaker)
    cache_repo = PostgresTranslationCacheRepository(AsyncSessionMaker)
    conversation_repo = PostgresConversationRepository(AsyncSessionMaker)
    learning_event_repo = PostgresLearningEventRepository(AsyncSessionMaker)
    skill_tracking_repo = PostgresSkillTrackingRepository(AsyncSessionMaker)
    kg_repo = KnowledgeGraphRepository(AsyncSessionMaker)

    # ---------------------------------------------------
    # Providers
    # ---------------------------------------------------

    translator_provider = LibreTranslateProvider()
    ocr_provider = PyTesseractProvider()
    llm_provider = OpenAIProvider()

    speech_provider = WhisperProvider()
    tts_provider = TextToSpeechProvider()

    # ---------------------------------------------------
    # Core services
    # ---------------------------------------------------

    translator = CachedTranslator(
        provider=translator_provider,
        cache_repo=cache_repo,
    )

    extractor = WordExtractionService()

    vocab_service = VocabularyService(
        translator,
        vocab_repo,
        extractor,
    )

    ocr_service = OCRService(ocr_provider)

    # ---------------------------------------------------
    # AI Learning Engine
    # ---------------------------------------------------

    memory_service = ConversationMemoryService()

    mistake_engine = MistakeEngine(llm_provider)

    drill_service = DrillGenerationService(llm_provider)

    skill_tracker = SkillTrackingService(skill_tracking_repo)

    brain_service = LanguageBrainService(
        mistake_engine,
        drill_service,
        skill_tracker,
    )

    conversation_vocab_service = ConversationVocabularyService(
        extractor,
        vocab_service,
        vocab_repo,
    )

    knowledge_graph = KnowledgeGraphService(vocab_repo, kg_repo)

    retention_engine = RetentionEngine()

    learning_event_service = LearningEventService(
        processors=[
            SkillUpdateProcessor(skill_tracker),
            RetentionProcessor(retention_engine, vocab_repo),
            KnowledgeGraphProcessor(knowledge_graph),
        ],
        repo=learning_event_repo,
    )

    conversation_service = ConversationService(
        llm_provider,
        vocab_repo,
        conversation_repo,
        brain_service,
        memory_service,
        conversation_vocab_service,
        skill_tracker,
        learning_event_service,
    )

    # ---------------------------------------------------
    # Learning System
    # ---------------------------------------------------

    graph_service = LearningGraphService(vocab_repo)

    lesson_service = LessonGenerationService(
        llm_provider,
        graph_service,
    )

    scenario_service = ScenarioService(llm_provider)

    # ---------------------------------------------------
    # Intelligence Layer
    # ---------------------------------------------------

    roadmap_service = LearningRoadmapService(
        graph_service,
        skill_tracker,
        retention_engine,
        vocab_repo,
    )

    # ---------------------------------------------------
    # Speech Conversation
    # ---------------------------------------------------

    speech_service = SpeechConversationService(
        speech_provider,
        tts_provider,
        conversation_service,
    )

    # ---------------------------------------------------
    # Middleware
    # ---------------------------------------------------

    limiter = RateLimiter(
        redis_url=settings.REDIS_URL if settings.ENABLE_REDIS_CACHE else None,
        limit=60,
        window_sec=60,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        user_id = getattr(getattr(request, "user", None), "id", None)
        path = request.url.path

        # rate limit selected heavy endpoints
        if any(path.startswith(p) for p in ["/speech", "/conversation", "/translate"]):
            allowed = await limiter.allow(f"{path}:{request.client.host}")
            if not allowed:
                return Response(status_code=429, content="Too Many Requests")

        start = time.time()
        error = ""

        try:
            response = await call_next(request)
        except Exception as exc:
            error = str(exc)
            response = Response(status_code=500, content="Internal Server Error")
            raise
        finally:
            duration = time.time() - start
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=path,
                status=getattr(response, "status_code", 0),
            ).observe(duration)
            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "endpoint": path,
                    "latency": duration,
                    "error": error,
                },
            )

        return response

    # ---------------------------------------------------
    # Health Check
    # ---------------------------------------------------

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        checks = {"db": False, "redis": False, "celery": False}
        try:
            from vocablens.infrastructure.db.session import engine
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            checks["db"] = True
        except Exception:
            checks["db"] = False

        try:
            if settings.ENABLE_REDIS_CACHE:
                import redis.asyncio as redis  # type: ignore
                r = redis.from_url(settings.REDIS_URL)
                await r.ping()
                checks["redis"] = True
        except Exception:
            checks["redis"] = False

        try:
            from vocablens.tasks.celery_app import celery_app
            pong = celery_app.control.ping(timeout=0.5)
            checks["celery"] = bool(pong)
        except Exception:
            checks["celery"] = False

        status = all(checks.values())
        return {"status": "ok" if status else "degraded", **checks}

    @app.get("/metrics")
    def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ---------------------------------------------------
    # Routes
    # ---------------------------------------------------

    app.include_router(
        create_routes(
            vocab_service,
            ocr_service,
            user_repo,
            conversation_service,
            speech_service,
            lesson_service,
            scenario_service,
            roadmap_service,
            knowledge_graph,
        )
    )

    return app


app = create_app()
