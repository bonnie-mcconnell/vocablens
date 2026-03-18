from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vocablens.auth.jwt import decode_token
from vocablens.domain.user import User
from vocablens.infrastructure.db.session import AsyncSessionMaker, get_session
from vocablens.infrastructure.jobs.celery_queue import CeleryJobQueue
from vocablens.infrastructure.jobs.base import JobQueue
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository
from vocablens.infrastructure.notifications.base import CompositeNotificationSink, NotificationSink
from vocablens.infrastructure.notifications.logging_notifier import LoggingNotificationSink
from vocablens.infrastructure.notifications.persistent_notifier import PersistentNotificationSink
from vocablens.infrastructure.notifications.webhook_notifier import WebhookNotificationSink
from vocablens.config.settings import settings
from vocablens.infrastructure.postgres_conversation_repository import PostgresConversationRepository
from vocablens.infrastructure.postgres_learning_event_repository import PostgresLearningEventRepository
from vocablens.infrastructure.postgres_skill_tracking_repository import PostgresSkillTrackingRepository
from vocablens.infrastructure.postgres_translation_cache_repository import PostgresTranslationCacheRepository
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory, UnitOfWork
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
from vocablens.services.explanation_service import ExplainMyThinkingService
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
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.scenario_service import ScenarioService
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.speech_conversation_service import SpeechConversationService
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.tutor_mode_service import TutorModeService
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.word_extraction_service import WordExtractionService

security = HTTPBearer()


def get_uow_factory():
    return UnitOfWorkFactory(AsyncSessionMaker)


def get_job_queue() -> JobQueue:
    return CeleryJobQueue()


def get_personalization_service(uow_factory=Depends(get_uow_factory)):
    from vocablens.services.personalization_service import PersonalizationService
    return PersonalizationService(uow_factory)


def get_tutor_mode_service() -> TutorModeService:
    return TutorModeService()


def get_notification_sink(uow_factory=Depends(get_uow_factory)) -> NotificationSink:
    sinks = [LoggingNotificationSink()]
    if settings.ENABLE_OUTBOUND_NOTIFICATIONS and settings.NOTIFICATION_WEBHOOK_URL:
        sinks.append(WebhookNotificationSink(settings.NOTIFICATION_WEBHOOK_URL))
    return PersistentNotificationSink(CompositeNotificationSink(*sinks), uow_factory)


def get_subscription_service(uow_factory=Depends(get_uow_factory)) -> SubscriptionService:
    return SubscriptionService(uow_factory)


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

def get_retention_engine(uow_factory=Depends(get_uow_factory)) -> RetentionEngine:
    return RetentionEngine(uow_factory)


def get_learning_engine(
    uow_factory=Depends(get_uow_factory),
    retention_engine=Depends(get_retention_engine),
    personalization=Depends(get_personalization_service),
    subscription_service=Depends(get_subscription_service),
):
    return LearningEngine(uow_factory, retention_engine, personalization, subscription_service)


async def get_skill_tracking_service(uow_factory=Depends(get_uow_factory)):
    return SkillTrackingService(uow_factory)


async def get_learning_event_service(
    uow_factory=Depends(get_uow_factory),
    skill_tracker=Depends(get_skill_tracking_service),
    job_queue=Depends(get_job_queue),
    personalization=Depends(get_personalization_service),
    notifier=Depends(get_notification_sink),
):
    retention = RetentionEngine(uow_factory)
    kg_service = KnowledgeGraphService(uow_factory)
    from vocablens.services.event_processors.enrichment_dispatcher import EnrichmentDispatchProcessor
    from vocablens.services.event_processors.embedding_dispatcher import EmbeddingDispatchProcessor
    from vocablens.services.event_processors.personalization_update_processor import PersonalizationUpdateProcessor
    from vocablens.services.event_processors.retention_notification_processor import RetentionNotificationProcessor
    from vocablens.services.event_processors.skill_snapshot_dispatcher import SkillSnapshotDispatcher
    processors = [
        SkillUpdateProcessor(skill_tracker),
        RetentionProcessor(retention, uow_factory),
        RetentionNotificationProcessor(retention, notifier),
        KnowledgeGraphProcessor(kg_service),
        PersonalizationUpdateProcessor(personalization),
        EnrichmentDispatchProcessor(job_queue),
        EmbeddingDispatchProcessor(job_queue),
        SkillSnapshotDispatcher(job_queue),
    ]
    return LearningEventService(processors=processors, uow_factory=uow_factory)


async def get_vocabulary_service(
    translator_provider=Depends(get_translation_provider),
    cache_repo=Depends(get_translation_cache_repo),
    learning_events=Depends(get_learning_event_service),
):
    translator = CachedTranslator(provider=translator_provider, cache_repo=cache_repo)
    extractor = WordExtractionService()
    uow_factory = UnitOfWorkFactory(AsyncSessionMaker)
    return VocabularyService(translator, uow_factory, extractor, events=learning_events)


async def get_conversation_service(
    llm_provider=Depends(get_llm_provider),
    uow_factory=Depends(get_uow_factory),
    skill_tracker=Depends(get_skill_tracking_service),
    learning_events=Depends(get_learning_event_service),
    vocab_service=Depends(get_vocabulary_service),
    learning_engine=Depends(get_learning_engine),
    tutor_mode_service=Depends(get_tutor_mode_service),
    subscription_service=Depends(get_subscription_service),
):
    mistake_engine = MistakeEngine(llm_provider, uow_factory)
    drill_service = DrillGenerationService(llm_provider)
    explanation_service = ExplainMyThinkingService(llm_provider)
    brain = LanguageBrainService(mistake_engine, drill_service, explanation_service, skill_tracker)
    memory = ConversationMemoryService()
    vocab_extractor = ConversationVocabularyService(
        WordExtractionService(),
        vocab_service,
        uow_factory,
    )
    return ConversationService(
        llm_provider,
        uow_factory,
        brain,
        memory,
        vocab_extractor,
        skill_tracker,
        learning_events,
        learning_engine,
        tutor_mode_service,
        subscription_service,
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
    uow_factory=Depends(get_uow_factory),
) -> LearningGraphService:
    return LearningGraphService(uow_factory)


def get_lesson_generation_service(
    llm_provider=Depends(get_llm_provider),
    graph_service=Depends(get_learning_graph_service),
    learning_engine=Depends(get_learning_engine),
) -> LessonGenerationService:
    return LessonGenerationService(llm_provider, graph_service, learning_engine)


def get_scenario_service(
    llm_provider=Depends(get_llm_provider),
) -> ScenarioService:
    return ScenarioService(llm_provider)


def get_knowledge_graph_service(
    uow_factory=Depends(get_uow_factory),
) -> KnowledgeGraphService:
    return KnowledgeGraphService(uow_factory)


def get_learning_roadmap_service(
    graph_service=Depends(get_learning_graph_service),
    skill_tracker=Depends(get_skill_tracking_service),
    retention_engine=Depends(get_retention_engine),
    uow_factory=Depends(get_uow_factory),
    learning_engine=Depends(get_learning_engine),
    personalization=Depends(get_personalization_service),
) -> LearningRoadmapService:
    return LearningRoadmapService(
        graph_service,
        skill_tracker,
        retention_engine,
        uow_factory,
        learning_engine,
        personalization,
    )


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

async def get_current_user(
    request: Request,
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

    request.scope["user"] = user
    return user
