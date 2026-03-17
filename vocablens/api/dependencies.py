from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vocablens.auth.jwt import decode_token
from vocablens.domain.user import User
from vocablens.infrastructure.db.session import AsyncSessionMaker, get_session
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository
from vocablens.infrastructure.postgres_conversation_repository import PostgresConversationRepository
from vocablens.infrastructure.postgres_learning_event_repository import PostgresLearningEventRepository
from vocablens.infrastructure.postgres_skill_tracking_repository import PostgresSkillTrackingRepository
from vocablens.infrastructure.postgres_translation_cache_repository import PostgresTranslationCacheRepository
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.providers.llm.openai_provider import OpenAIProvider
from vocablens.providers.ocr.pytesseract_provider import PyTesseractProvider
from vocablens.providers.speech.tts_provider import TextToSpeechProvider
from vocablens.providers.speech.whisper_provider import WhisperProvider
from vocablens.providers.translation.libretranslate_provider import LibreTranslateProvider
from vocablens.services.cached_translator import CachedTranslator
from vocablens.services.conversation_memory_service import ConversationMemoryService
from vocablens.services.conversation_service import ConversationService
from vocablens.services.conversation_vocab_service import ConversationVocabularyService
from vocablens.services.drill_generation_service import DrillGenerationService
from vocablens.services.event_processors.knowledge_graph_processor import KnowledgeGraphProcessor
from vocablens.services.event_processors.retention_processor import RetentionProcessor
from vocablens.services.event_processors.skill_update_processor import SkillUpdateProcessor
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.language_brain_service import LanguageBrainService
from vocablens.services.learning_event_service import LearningEventService
from vocablens.services.learning_graph_service import LearningGraphService
from vocablens.services.learning_roadmap_service import LearningRoadmapService
from vocablens.services.lesson_generation_service import LessonGenerationService
from vocablens.services.mistake_engine import MistakeEngine
from vocablens.services.ocr_service import OCRService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.scenario_service import ScenarioService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.speech_conversation_service import SpeechConversationService
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.word_extraction_service import WordExtractionService

security = HTTPBearer()


# --------------------------------------------------------------------------
# Repository providers
# --------------------------------------------------------------------------

async def get_user_repo(session=Depends(get_session)):
    return PostgresUserRepository(session)


async def get_vocab_repo(session=Depends(get_session)):
    return PostgresVocabularyRepository(session)


async def get_translation_cache_repo(session=Depends(get_session)):
    return PostgresTranslationCacheRepository(session)


async def get_conversation_repo(session=Depends(get_session)):
    return PostgresConversationRepository(session)


async def get_learning_event_repo(session=Depends(get_session)):
    return PostgresLearningEventRepository(session)


async def get_skill_tracking_repo(session=Depends(get_session)):
    return PostgresSkillTrackingRepository(session)


async def get_knowledge_graph_repo(session=Depends(get_session)):
    return KnowledgeGraphRepository(session)


# --------------------------------------------------------------------------
# Providers (LLM / translation / speech / OCR)
# --------------------------------------------------------------------------

def get_translation_provider() -> LibreTranslateProvider:
    return LibreTranslateProvider()


def get_llm_provider() -> OpenAIProvider:
    return OpenAIProvider()


def get_whisper_provider() -> WhisperProvider:
    return WhisperProvider()


def get_tts_provider() -> TextToSpeechProvider:
    return TextToSpeechProvider()


def get_ocr_provider() -> PyTesseractProvider:
    return PyTesseractProvider()


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

def get_retention_engine() -> RetentionEngine:
    return RetentionEngine()


async def get_skill_tracking_service(repo=Depends(get_skill_tracking_repo)):
    return SkillTrackingService(repo)


async def get_learning_event_service(
    repo=Depends(get_learning_event_repo),
    skill_tracker=Depends(get_skill_tracking_service),
    retention_repo=Depends(get_vocab_repo),
    knowledge_graph_repo=Depends(get_knowledge_graph_repo),
):
    retention = RetentionEngine()
    kg_service = KnowledgeGraphService(retention_repo, knowledge_graph_repo)
    processors = [
        SkillUpdateProcessor(skill_tracker),
        RetentionProcessor(retention, retention_repo),
        KnowledgeGraphProcessor(kg_service),
    ]
    return LearningEventService(processors=processors, repo=repo)


async def get_vocabulary_service(
    translator_provider=Depends(get_translation_provider),
    cache_repo=Depends(get_translation_cache_repo),
):
    translator = CachedTranslator(provider=translator_provider, cache_repo=cache_repo)
    extractor = WordExtractionService()
    uow_factory = UnitOfWorkFactory(AsyncSessionMaker)
    return VocabularyService(translator, uow_factory, extractor)


async def get_conversation_service(
    llm_provider=Depends(get_llm_provider),
    vocab_repo=Depends(get_vocab_repo),
    conversation_repo=Depends(get_conversation_repo),
    skill_tracker=Depends(get_skill_tracking_service),
    learning_events=Depends(get_learning_event_service),
    vocab_service=Depends(get_vocabulary_service),
):
    mistake_engine = MistakeEngine(llm_provider)
    drill_service = DrillGenerationService(llm_provider)
    brain = LanguageBrainService(mistake_engine, drill_service, skill_tracker)
    memory = ConversationMemoryService()
    vocab_extractor = ConversationVocabularyService(
        WordExtractionService(),
        vocab_service,
        vocab_repo,
    )
    return ConversationService(
        llm_provider,
        vocab_repo,
        conversation_repo,
        brain,
        memory,
        vocab_extractor,
        skill_tracker,
        learning_events,
    )


async def get_speech_conversation_service(
    speech_provider=Depends(get_whisper_provider),
    tts_provider=Depends(get_tts_provider),
    conversation_service=Depends(get_conversation_service),
):
    return SpeechConversationService(
        speech_provider,
        tts_provider,
        conversation_service,
    )


def get_ocr_service(provider=Depends(get_ocr_provider)) -> OCRService:
    return OCRService(provider)


def get_learning_graph_service(
    vocab_repo=Depends(get_vocab_repo),
) -> LearningGraphService:
    return LearningGraphService(vocab_repo)


def get_lesson_generation_service(
    llm_provider=Depends(get_llm_provider),
    graph_service=Depends(get_learning_graph_service),
) -> LessonGenerationService:
    return LessonGenerationService(llm_provider, graph_service)


def get_scenario_service(
    llm_provider=Depends(get_llm_provider),
) -> ScenarioService:
    return ScenarioService(llm_provider)


def get_knowledge_graph_service(
    vocab_repo=Depends(get_vocab_repo),
    knowledge_graph_repo=Depends(get_knowledge_graph_repo),
) -> KnowledgeGraphService:
    return KnowledgeGraphService(vocab_repo, knowledge_graph_repo)


def get_learning_roadmap_service(
    graph_service=Depends(get_learning_graph_service),
    skill_tracker=Depends(get_skill_tracking_service),
    retention_engine=Depends(get_retention_engine),
    vocab_repo=Depends(get_vocab_repo),
) -> LearningRoadmapService:
    return LearningRoadmapService(
        graph_service,
        skill_tracker,
        retention_engine,
        vocab_repo,
    )


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo=Depends(get_user_repo),
) -> User:

    try:
        user_id = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )

    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
