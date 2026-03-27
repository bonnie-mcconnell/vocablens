import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vocablens.auth.jwt import decode_token
from vocablens.config.settings import settings
from vocablens.domain.user import User
from vocablens.infrastructure.db.session import AsyncSessionMaker, get_session
from vocablens.infrastructure.jobs.base import JobQueue
from vocablens.infrastructure.jobs.celery_queue import CeleryJobQueue
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository
from vocablens.infrastructure.notifications.base import CompositeNotificationSink, NotificationSink
from vocablens.infrastructure.notifications.logging_notifier import LoggingNotificationSink
from vocablens.infrastructure.notifications.webhook_notifier import WebhookNotificationSink
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
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.notification_delivery_service import (
    EmailDeliveryBackend,
    InAppDeliveryBackend,
    NotificationDeliveryService,
    NotificationDeliverySink,
    PushDeliveryBackend,
)
from vocablens.services.ocr_service import OCRService
from vocablens.services.tutor_mode_service import TutorModeService
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


def get_notification_delivery_service(uow_factory=Depends(get_uow_factory)) -> NotificationDeliveryService:
    email_provider = LoggingNotificationSink()
    if settings.ENABLE_OUTBOUND_NOTIFICATIONS and settings.NOTIFICATION_WEBHOOK_URL:
        email_provider = CompositeNotificationSink(
            email_provider,
            WebhookNotificationSink(settings.NOTIFICATION_WEBHOOK_URL),
        )
    backends = {
        "email": EmailDeliveryBackend(email_provider),
        "push": PushDeliveryBackend(),
        "in_app": InAppDeliveryBackend(),
    }
    return NotificationDeliveryService(uow_factory, backends)


def get_notification_sink(
    delivery_service=Depends(get_notification_delivery_service),
) -> NotificationSink:
    return NotificationDeliverySink(delivery_service)


def get_notification_decision_engine(
    uow_factory=Depends(get_uow_factory),
) -> NotificationDecisionEngine:
    return NotificationDecisionEngine(uow_factory)


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


def get_ocr_service(provider=Depends(get_ocr_provider)) -> OCRService:
    return OCRService(provider)


def get_cached_translator(
    translator_provider=Depends(get_translation_provider),
    cache_repo=Depends(get_translation_cache_repo),
) -> CachedTranslator:
    return CachedTranslator(provider=translator_provider, cache_repo=cache_repo)


def get_word_extractor() -> WordExtractionService:
    return WordExtractionService()


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


def get_admin_token(request: Request) -> str:
    token = request.headers.get("X-Admin-Token", "")
    if not settings.ADMIN_TOKEN or not token or not secrets.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return token
