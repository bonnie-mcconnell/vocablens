from pathlib import Path
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from vocablens.infrastructure.database import init_db
from vocablens.infrastructure.repositories import SQLiteVocabularyRepository
from vocablens.infrastructure.repositories_users import SQLiteUserRepository
from vocablens.infrastructure.repositories_translation_cache import (
    SQLiteTranslationCacheRepository,
)

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

# Event processors
from vocablens.services.event_processors.skill_update_processor import SkillUpdateProcessor
from vocablens.services.event_processors.retention_processor import RetentionProcessor
from vocablens.services.event_processors.knowledge_graph_processor import KnowledgeGraphProcessor

# Routes
from vocablens.api.routes import create_routes


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

    # ---------------------------------------------------
    # Repositories
    # ---------------------------------------------------

    vocab_repo = SQLiteVocabularyRepository(db_path)
    user_repo = SQLiteUserRepository(db_path)
    cache_repo = SQLiteTranslationCacheRepository(str(db_path))

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

    skill_tracker = SkillTrackingService()

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

    conversation_service = ConversationService(
        llm_provider,
        vocab_repo,
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

    knowledge_graph = KnowledgeGraphService(vocab_repo)

    retention_engine = RetentionEngine()

    roadmap_service = LearningRoadmapService(
        graph_service,
        skill_tracker,
        retention_engine,
        vocab_repo,
    )

    learning_event_service = LearningEventService(
        processors=[
            SkillUpdateProcessor(skill_tracker),
            RetentionProcessor(retention_engine, vocab_repo),
            KnowledgeGraphProcessor(knowledge_graph),
        ],
        db_path=str(db_path),
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

    # ---------------------------------------------------
    # Health Check
    # ---------------------------------------------------

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------------------------------------------------
    # Startup
    # ---------------------------------------------------

    @app.on_event("startup")
    async def startup():

        init_db(db_path)

        logger.info("Database initialized")

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
